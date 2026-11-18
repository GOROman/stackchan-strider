import AppKit
import CoreBluetooth

private let serviceID = CBUUID(string: "48a23901-7920-49ee-889b-93d7dd615b02")
private let commandID = CBUUID(string: "48a23902-7920-49ee-889b-93d7dd615b02")
private let stateID = CBUUID(string: "48a23903-7920-49ee-889b-93d7dd615b02")
private let cyan = NSColor(srgbRed: 0.19, green: 0.89, blue: 0.95, alpha: 1)
private let yellow = NSColor(srgbRed: 1, green: 0.89, blue: 0.36, alpha: 1)

final class Link: NSObject, CBCentralManagerDelegate, CBPeripheralDelegate {
    var onStatus: (String) -> Void = { _ in }
    var onReady: (Int, UInt8, Int) -> Void = { _, _, _ in }
    var onClosed: () -> Void = {}
    private lazy var manager = CBCentralManager(delegate: self, queue: .main)
    private var peripheral: CBPeripheral?
    private var writer: CBCharacteristic?
    private var verified = false
    private var waiting = false
    private var pending: Data?
    private var timeout: Timer?

    func start() {
        _ = manager
    }

    func toggle() {
        if manager.isScanning || peripheral != nil {
            close("切断しました")
        } else if manager.state == .poweredOn {
            onStatus("Strider を検索中…")
            manager.scanForPeripherals(withServices: [serviceID])
            timeout = Timer.scheduledTimer(withTimeInterval: 15, repeats: false) { [weak self] _ in
                self?.close("Strider が見つかりません")
            }
        } else {
            centralManagerDidUpdateState(manager)
        }
    }

    func send(direction: Int, speed: Int, pitch: Int, flags: UInt8) {
        guard verified else { return }
        pending = Data([UInt8(direction), UInt8(speed), UInt8(pitch), flags])
        flush()
    }

    private func flush() {
        guard let peripheral, let writer, let data = pending, !waiting else { return }
        pending = nil
        waiting = true
        peripheral.writeValue(data, for: writer, type: .withResponse)
    }

    private func close(_ status: String) {
        timeout?.invalidate()
        timeout = nil
        manager.stopScan()
        let previous = peripheral
        peripheral = nil
        writer = nil
        pending = nil
        verified = false
        waiting = false
        if let previous { manager.cancelPeripheralConnection(previous) }
        onClosed()
        onStatus(status)
    }

    func centralManagerDidUpdateState(_ central: CBCentralManager) {
        switch central.state {
        case .poweredOn: onStatus("未接続")
        case .unauthorized: close("macOS 設定で Bluetooth を許可してください")
        case .poweredOff: close("Bluetooth をオンにしてください")
        case .unsupported: close("この Mac は Bluetooth LE に対応していません")
        default: break
        }
    }

    func centralManager(_ central: CBCentralManager, didDiscover device: CBPeripheral,
                        advertisementData: [String: Any], rssi: NSNumber) {
        guard peripheral == nil else { return }
        peripheral = device
        central.stopScan()
        onStatus("\(device.name ?? "Strider") に接続中…")
        central.connect(device)
    }

    func centralManager(_ central: CBCentralManager, didConnect device: CBPeripheral) {
        guard peripheral === device else { return }
        device.delegate = self
        device.discoverServices([serviceID])
    }

    func centralManager(_ central: CBCentralManager, didFailToConnect device: CBPeripheral, error: Error?) {
        if peripheral === device { close(error?.localizedDescription ?? "接続できませんでした") }
    }

    func centralManager(_ central: CBCentralManager, didDisconnectPeripheral device: CBPeripheral, error: Error?) {
        if peripheral === device { close("Bluetooth 接続が切れました") }
    }

    func peripheral(_ device: CBPeripheral, didDiscoverServices error: Error?) {
        guard peripheral === device else { return }
        guard let service = device.services?.first, error == nil else {
            close("Strider のサービスを読み取れません")
            return
        }
        device.discoverCharacteristics([commandID, stateID], for: service)
    }

    func peripheral(_ device: CBPeripheral, didDiscoverCharacteristicsFor service: CBService, error: Error?) {
        guard peripheral === device else { return }
        guard let characteristics = service.characteristics,
              let command = characteristics.first(where: { $0.uuid == commandID }),
              let state = characteristics.first(where: { $0.uuid == stateID }), error == nil else {
            close("Strider の操作チャンネルを開けません")
            return
        }
        writer = command
        device.readValue(for: state)
    }

    func peripheral(_ device: CBPeripheral, didUpdateValueFor characteristic: CBCharacteristic, error: Error?) {
        guard peripheral === device, characteristic.uuid == stateID, !verified else { return }
        guard let state = characteristic.value, state.count >= 6, error == nil else {
            close("Strider の状態を取得できません")
            return
        }
        timeout?.invalidate()
        timeout = nil
        verified = true
        onStatus("\(device.name ?? "Strider") に接続")
        let maxDrive = state.count >= 7 ? min(100, max(10, Int(state[6]))) : 60
        onReady(min(Int(state[2]), 60), state[3] & 3, maxDrive)
    }

    func peripheral(_ device: CBPeripheral, didWriteValueFor characteristic: CBCharacteristic, error: Error?) {
        guard peripheral === device, characteristic.uuid == commandID else { return }
        waiting = false
        if let error { close(error.localizedDescription) } else { flush() }
    }
}

final class ControlPad: NSView {
    var onDrive: (CGFloat) -> Void = { _ in }
    var onPitch: (Int) -> Void = { _ in }
    var enabled = false { didSet { if !enabled { stop(animated: false) }; needsDisplay = true } }
    var pitch = 30 { didSet { needsDisplay = true } }
    private var drive: CGFloat = 0
    private var returnTimer: Timer?
    private var driveTouch: NSTouch?
    private var pitchTouch: NSTouch?
    private var mouseDrag = false
    private var origin: CGFloat = 0
    private var pitchOrigin = 30
    private var cursor: NSPoint?
    private var track: NSRect { bounds.insetBy(dx: 18, dy: 18) }

    override init(frame: NSRect) {
        super.init(frame: frame)
        allowedTouchTypes = [.indirect]
    }

    required init?(coder: NSCoder) { nil }

    func stop(animated: Bool = true) {
        driveTouch = nil
        pitchTouch = nil
        mouseDrag = false
        neutral(animated: animated)
    }

    private func neutral(animated: Bool = true) {
        returnTimer?.invalidate()
        returnTimer = nil
        cursor = nil
        onDrive(0)
        if !animated || drive == 0 {
            drive = 0
            needsDisplay = true
            return
        }
        let from = drive
        let started = ProcessInfo.processInfo.systemUptime
        let timer = Timer(timeInterval: 1.0 / 60, repeats: true) { [weak self] timer in
            guard let self else { timer.invalidate(); return }
            let remaining = max(0, 1 - (ProcessInfo.processInfo.systemUptime - started) / 0.32)
            self.drive = from * CGFloat(remaining * remaining)
            self.needsDisplay = true
            if remaining == 0 {
                timer.invalidate()
                self.returnTimer = nil
            }
        }
        returnTimer = timer
        RunLoop.main.add(timer, forMode: .common)
        needsDisplay = true
    }

    override func draw(_ dirtyRect: NSRect) {
        NSColor.black.setFill()
        bounds.fill()
        let box = track
        guard box.width > 0, box.height > 0 else { return }
        let shape = NSBezierPath(roundedRect: box, xRadius: 22, yRadius: 22)
        NSGraphicsContext.saveGraphicsState()
        shape.addClip()
        yellow.setFill()
        NSRect(x: box.minX, y: box.minY, width: box.width, height: box.height / 2).fill()
        cyan.setFill()
        NSRect(x: box.minX, y: box.midY, width: box.width, height: box.height / 2).fill()
        NSColor.black.setFill()
        NSRect(x: box.minX, y: box.midY - 2, width: box.width, height: 4).fill()
        NSGraphicsContext.restoreGraphicsState()

        let y = box.midY + drive * max(0, box.height / 2 - 25)
        let thumb = NSRect(x: box.midX - 46, y: y - 19, width: 92, height: 38)
        NSColor.black.setFill()
        NSBezierPath(roundedRect: thumb, xRadius: 14, yRadius: 14).fill()
        if let cursor {
            let ring = NSBezierPath(ovalIn: NSRect(x: cursor.x - 26, y: cursor.y - 26, width: 52, height: 52))
            NSColor.black.setStroke()
            ring.lineWidth = 9
            ring.stroke()
            yellow.setStroke()
            ring.lineWidth = 4
            ring.stroke()
        }
        let ink: [NSAttributedString.Key: Any] = [.font: NSFont.boldSystemFont(ofSize: 15), .foregroundColor: NSColor.black]
        let top = enabled ? "前進" : "未接続"
        (top as NSString).draw(at: NSPoint(x: box.minX + 14, y: box.maxY - 26), withAttributes: ink)
        ("後退" as NSString).draw(at: NSPoint(x: box.minX + 14, y: box.minY + 8), withAttributes: ink)
    }

    private func updateDrive(_ value: CGFloat, at point: NSPoint) {
        returnTimer?.invalidate()
        returnTimer = nil
        let value = min(1, max(-1, value))
        drive = abs(value) < 0.035 ? 0 : value
        cursor = point
        onDrive(drive)
        needsDisplay = true
    }

    override func mouseDown(with event: NSEvent) {
        guard enabled, driveTouch == nil else { return }
        mouseDrag = true
        mouseDragged(with: event)
    }

    override func mouseDragged(with event: NSEvent) {
        guard mouseDrag, track.height > 0 else { return }
        let point = convert(event.locationInWindow, from: nil)
        updateDrive((point.y - track.midY) / (track.height / 2), at: point)
    }

    override func mouseUp(with event: NSEvent) {
        if mouseDrag { mouseDrag = false; neutral() }
    }

    override func touchesBegan(with event: NSEvent) {
        guard enabled, !mouseDrag, window?.isKeyWindow == true else { return }
        for touch in event.touches(matching: .began, in: self) {
            if driveTouch == nil && pitchTouch == nil {
                driveTouch = touch
                origin = touch.normalizedPosition.y
                updateDrive(0, at: NSPoint(x: track.midX, y: track.midY))
            } else if driveTouch != nil && pitchTouch == nil {
                pitchTouch = touch
                pitchOrigin = pitch
            }
        }
    }

    override func touchesMoved(with event: NSEvent) {
        for touch in event.touches(matching: .moved, in: self) {
            let point = touch.normalizedPosition
            if driveTouch?.identity.isEqual(touch.identity) == true {
                let delta = point.y - origin
                let available = delta >= 0 ? 1 - origin : origin
                let travel = max(0.10, available * 0.75)
                let value = delta / travel
                let y = track.midY + min(1, max(-1, value)) * track.height / 2
                updateDrive(value, at: NSPoint(x: track.minX + point.x * track.width, y: y))
            } else if let second = pitchTouch, second.identity.isEqual(touch.identity) {
                onPitch(min(60, max(0, pitchOrigin + Int(((point.y - second.normalizedPosition.y) * 60).rounded()))))
            }
        }
    }

    override func touchesEnded(with event: NSEvent) {
        for touch in event.touches(matching: .ended, in: self) {
            if driveTouch?.identity.isEqual(touch.identity) == true { driveTouch = nil; neutral() }
            if pitchTouch?.identity.isEqual(touch.identity) == true { pitchTouch = nil }
        }
    }

    override func touchesCancelled(with event: NSEvent) { stop() }
}

final class App: NSObject, NSApplicationDelegate, NSWindowDelegate {
    private let link = Link()
    private let pad = ControlPad(frame: .zero)
    private let status = NSTextField(labelWithString: "未接続")
    private let motion = NSTextField(labelWithString: "停止")
    private let pitchLabel = NSTextField(labelWithString: "顔の上下角度 30°")
    private let pitch = NSSlider(value: 30, minValue: 0, maxValue: 60, target: nil, action: nil)
    private let connect = NSButton(title: "Bluetooth で接続", target: nil, action: nil)
    private let center = NSButton(title: "センタリング", target: nil, action: nil)
    private let halt = NSButton(title: "停止", target: nil, action: nil)
    private let animate = NSButton(checkboxWithTitle: "歩行に連動して顔を動かす", target: nil, action: nil)
    private let invert = NSButton(checkboxWithTitle: "前進と後退を入れ替える", target: nil, action: nil)
    private var window: NSWindow!
    private var heartbeat: Timer?
    private var direction = 0
    private var speed = 35
    private var maxDrive = 60

    func applicationDidFinishLaunching(_ notification: Notification) {
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 700, height: 530),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "Stackchan Strider"
        window.minSize = NSSize(width: 555, height: 420)
        window.backgroundColor = .black
        window.appearance = NSAppearance(named: .darkAqua)
        window.delegate = self

        let title = NSTextField(labelWithString: "Stackchan Strider")
        title.font = .boldSystemFont(ofSize: 27)
        title.textColor = cyan
        status.textColor = cyan
        motion.font = .monospacedDigitSystemFont(ofSize: 24, weight: .bold)
        motion.textColor = yellow
        let help = NSTextField(wrappingLabelWithString: "カーソルを縦スライダーの上へ。\n1 本指を上下に動かして歩行、2 本目で顔の角度を調整。\n歩行側の指を離すと停止します。クリックドラッグも使えます。")
        help.maximumNumberOfLines = 0
        help.textColor = cyan

        let controls = NSStackView(views: [title, status, connect, motion, pitchLabel, pitch, animate, invert, halt, center, help])
        controls.orientation = .vertical
        controls.alignment = .leading
        controls.spacing = 9
        let layout = NSStackView(views: [controls, pad])
        layout.orientation = .horizontal
        layout.alignment = .centerY
        layout.spacing = 16
        layout.edgeInsets = NSEdgeInsets(top: 12, left: 20, bottom: 12, right: 12)
        window.contentView = layout
        pad.translatesAutoresizingMaskIntoConstraints = false
        NSLayoutConstraint.activate([
            pad.widthAnchor.constraint(greaterThanOrEqualToConstant: 180),
            pad.heightAnchor.constraint(equalTo: layout.heightAnchor, constant: -24),
            controls.widthAnchor.constraint(equalToConstant: 300),
            pitch.widthAnchor.constraint(equalToConstant: 240),
            help.widthAnchor.constraint(equalTo: controls.widthAnchor)
        ])

        connect.target = self
        connect.action = #selector(toggleLink)
        center.target = self
        center.action = #selector(centerPosition)
        halt.target = self
        halt.action = #selector(stop)
        pitch.target = self
        pitch.action = #selector(pitchChanged)
        pitch.isContinuous = true
        for button in [animate, invert] {
            button.target = self
            button.action = #selector(send)
        }
        pad.onDrive = { [weak self] in self?.drive($0) }
        pad.onPitch = { [weak self] in self?.setPitch($0) }
        link.onStatus = { [weak self] in self?.status.stringValue = $0 }
        link.onClosed = { [weak self] in self?.setConnected(false) }
        link.onReady = { [weak self] angle, flags, maxDrive in
            guard let self else { return }
            self.maxDrive = maxDrive
            self.speed = min(self.speed, maxDrive)
            self.animate.state = flags & 2 != 0 ? .on : .off
            self.invert.state = flags & 1 != 0 ? .on : .off
            self.setConnected(true)
            self.setPitch(angle)
        }
        setConnected(false)
        link.start()
        heartbeat = Timer(timeInterval: 0.3, repeats: true) { [weak self] _ in
            if let self, self.direction != 0 { self.send() }
        }
        RunLoop.main.add(heartbeat!, forMode: .common)
        window.center()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    private func setConnected(_ value: Bool) {
        pad.enabled = value
        connect.title = value ? "切断" : "Bluetooth で接続"
        for control in [pitch, animate, invert, center, halt] { control.isEnabled = value }
    }

    private func drive(_ value: CGFloat) {
        direction = value > 0 ? 1 : value < 0 ? 2 : 0
        if direction != 0 { speed = 9 + max(1, Int((abs(value) * CGFloat(maxDrive - 9)).rounded())) }
        motion.stringValue = direction == 0 ? "停止" : "\(direction == 1 ? "前進" : "後退") \(speed)%"
        send()
    }

    private func setPitch(_ value: Int) {
        pitch.integerValue = value
        pitchLabel.stringValue = "顔の上下角度 \(value)°"
        pad.pitch = value
        send()
    }

    @objc private func send() {
        let flags: UInt8 = (invert.state == .on ? 1 : 0) | (animate.state == .on ? 2 : 0)
        link.send(direction: direction, speed: speed, pitch: pitch.integerValue, flags: flags)
    }

    @objc private func toggleLink() { link.toggle() }
    @objc private func pitchChanged() { setPitch(pitch.integerValue) }
    @objc private func stop() { pad.stop() }
    @objc private func centerPosition() { pitch.integerValue = 30; stop(); setPitch(30) }

    func applicationDidResignActive(_ notification: Notification) { stop() }
    func windowDidResignKey(_ notification: Notification) { stop() }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
    func applicationWillTerminate(_ notification: Notification) { stop() }
}

let application = NSApplication.shared
let delegate = App()
application.setActivationPolicy(.regular)
application.delegate = delegate
application.run()
