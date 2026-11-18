// Stackchan Strider for M5Stack K151 / CoreS3.
#include <Arduino.h>
#include <Avatar.h>
#include <BLEDevice.h>
#include <M5StackChan.h>
#include <Preferences.h>

namespace {

constexpr char SERVICE_UUID[] = "48a23901-7920-49ee-889b-93d7dd615b02";
constexpr char COMMAND_UUID[] = "48a23902-7920-49ee-889b-93d7dd615b02";
constexpr char STATE_UUID[] = "48a23903-7920-49ee-889b-93d7dd615b02";
constexpr uint32_t COMMAND_TIMEOUT_MS = 900;
constexpr uint32_t REACTION_MS = 650;
constexpr uint32_t ANIMATION_INTERVAL_MS = 50;
// StackChan-BSP reports yaw in tenths of a degree and clamps it to ±128°.
constexpr float YAW_REPORT_LIMIT = 1280.0f;
constexpr int PITCH_CENTER = 30;
constexpr int PITCH_MAX = 60;
constexpr int DRIVE_MIN = 10;
constexpr int DRIVE_MAX = 100;
constexpr uint32_t BRAKE_MS = 320;
constexpr uint32_t BRAKE_STEP_MS = 20;

struct Command {
    uint8_t direction;  // 0 stop, 1 forward, 2 reverse
    uint8_t speed;
    uint8_t pitch;
    uint8_t flags;  // bit 0 invert, bit 1 animate
};
static_assert(sizeof(Command) == 4);

Preferences prefs;
m5avatar::Avatar avatar;
BLECharacteristic* state;
Command active{0, 35, PITCH_CENTER, 0};
Command pending{};
uint32_t pendingAt = 0;
uint32_t lastCommandAt = 0;
uint32_t reactionUntil = 0;
uint32_t lastAnimationAt = 0;
int lastPitchTarget = -1;
int driveOutput = 0;
int brakeFrom = 0;
uint32_t brakeStartedAt = 0;
bool hasCommand = false;
bool connected = false;
bool disconnected = false;
portMUX_TYPE mailboxLock = portMUX_INITIALIZER_UNLOCKED;

void setDriveOutput(int output) {
    if (output != driveOutput) {
        driveOutput = output;
        M5StackChan.Motion.rotateX(output);
    }
}

void applyDrive(uint32_t now) {
    if (active.direction == 0) {
        if (driveOutput && !brakeFrom) {
            brakeFrom = driveOutput;
            brakeStartedAt = now;
        }
        return;
    }

    brakeFrom = 0;
    const int direction = active.direction == 1 ? 1 : -1;
    const int sign = (active.flags & 1) ? 1 : -1;
    setDriveOutput(direction * sign * active.speed * 10);
}

void updateBraking(uint32_t now) {
    if (!brakeFrom) {
        return;
    }
    const uint32_t elapsed = now - brakeStartedAt;
    if (elapsed >= BRAKE_MS) {
        brakeFrom = 0;
        setDriveOutput(0);
        return;
    }
    const uint32_t step = elapsed / BRAKE_STEP_MS * BRAKE_STEP_MS;
    const float remaining = 1.0f - static_cast<float>(step) / BRAKE_MS;
    setDriveOutput(lroundf(brakeFrom * remaining * remaining));
}

void updateAnimation(uint32_t now) {
    if (now - lastAnimationAt < ANIMATION_INTERVAL_MS) {
        return;
    }
    lastAnimationAt = now;

    using m5avatar::Expression;
    Expression expression = Expression::Neutral;
    float mouth = 0;
    int target = active.pitch;
    int pitchSpeed = 450;
    if (active.direction && (active.flags & 2)) {
        const float effort = (active.speed - DRIVE_MIN) / static_cast<float>(DRIVE_MAX - DRIVE_MIN);
        const bool reversing = active.direction == 2;
        const int yaw = M5StackChan.Motion.getCurrentYawAngle();
        // Both ends yield the same pitch when the yaw reading wraps.
        const float stride = cosf(PI * yaw / YAW_REPORT_LIMIT);
        const bool surprised = static_cast<int32_t>(reactionUntil - now) > 0;
        if (surprised) {
            mouth = 0.95f;
        } else if (active.speed >= 48) {
            expression = stride > 0 ? Expression::Angry : Expression::Neutral;
            mouth = 0.24f + 0.12f * stride;
        } else if (reversing && stride < -0.45f) {
            expression = Expression::Doubt;
            mouth = 0.18f;
        } else {
            mouth = 0.10f + 0.08f * stride;
        }
        const float nodRange = 2.0f + 3.0f * effort;
        const int lookAngle = active.pitch + (reversing ? 18 : -6);
        const float base = constrain(static_cast<float>(lookAngle), nodRange, PITCH_MAX - nodRange);
        target = lroundf(base + stride * nodRange);
        pitchSpeed = reversing ? 850 : 650;
    }
    avatar.setExpression(expression);
    avatar.setMouthOpenRatio(mouth);

    target = constrain(target, 0, PITCH_MAX);
    if (target != lastPitchTarget) {
        M5StackChan.Motion.movePitch(target * 10, pitchSpeed);
        lastPitchTarget = target;
    }
}

void publishState() {
    const uint16_t mv = constrain(lroundf(M5StackChan.getBatteryVoltage() * 1000), 0L, 65535L);
    const uint8_t value[]{active.direction, active.speed, active.pitch, active.flags,
                          static_cast<uint8_t>(mv), static_cast<uint8_t>(mv >> 8), DRIVE_MAX};
    state->setValue(value, sizeof(value));
}

void applyCommand(const Command& command, uint32_t now) {
    if (command.direction != active.direction) {
        lastAnimationAt = now - ANIMATION_INTERVAL_MS;
    }
    if (command.direction && command.speed >= 48 &&
        (active.direction != command.direction || active.speed < 48 || command.speed >= active.speed + 12)) {
        reactionUntil = now + REACTION_MS;
    }
    if (!command.direction) {
        reactionUntil = now;
    }
    const uint8_t changed = command.flags ^ active.flags;
    if (changed & 1) {
        prefs.putBool("invert", command.flags & 1);
    }
    if (changed & 2) {
        prefs.putBool("animate", command.flags & 2);
    }
    const bool driveChanged = command.direction != active.direction || command.speed != active.speed || (changed & 1);
    active = command;
    if (driveChanged) {
        applyDrive(now);
    }
}

class ServerCallbacks : public BLEServerCallbacks {
    void onConnect(BLEServer*) override {
        portENTER_CRITICAL(&mailboxLock);
        connected = true;
        portEXIT_CRITICAL(&mailboxLock);
    }

    void onDisconnect(BLEServer*) override {
        portENTER_CRITICAL(&mailboxLock);
        connected = false;
        disconnected = true;
        hasCommand = false;
        portEXIT_CRITICAL(&mailboxLock);
    }
};

class CommandCallbacks : public BLECharacteristicCallbacks {
    void onWrite(BLECharacteristic* characteristic) override {
        if (characteristic->getLength() != sizeof(Command)) {
            return;
        }
        const uint8_t* data = characteristic->getData();
        const Command command{data[0], data[1], data[2], data[3]};
        if (command.direction > 2 || command.speed < DRIVE_MIN || command.speed > DRIVE_MAX ||
            command.pitch > PITCH_MAX || command.flags > 3) {
            return;
        }
        const uint32_t now = millis();
        portENTER_CRITICAL(&mailboxLock);
        if (connected && !disconnected) {
            pending = command;
            pendingAt = now;
            hasCommand = true;
        }
        portEXIT_CRITICAL(&mailboxLock);
    }
};

ServerCallbacks serverCallbacks;
CommandCallbacks commandCallbacks;

}  // namespace

void setup() {
    M5StackChan.begin();
    M5.Display.setBrightness(120);
    Serial.begin(115200);
    // PWM writes set the output but do not enable servo torque. BSP idle
    // release can also turn torque off while yaw is in continuous mode.
    M5StackChan.Motion.setAutoTorqueReleaseEnabled(false);
    M5StackChan.Motion.rotateX(0);
    M5StackChan.Motion.setTorqueEnabled(true);
    M5StackChan.Motion.movePitch(PITCH_CENTER * 10, 300);
    lastPitchTarget = PITCH_CENTER;
    prefs.begin("strider", false);
    active.flags = (prefs.getBool("invert", false) ? 1 : 0) |
                   (prefs.getBool("animate", true) ? 2 : 0);
    avatar.start();

    char name[24];
    snprintf(name, sizeof(name), "Strider-%04X", static_cast<unsigned>((ESP.getEfuseMac() >> 32) & 0xFFFF));
    BLEDevice::init(name);
    BLEServer* server = BLEDevice::createServer();
    server->setCallbacks(&serverCallbacks);
    server->advertiseOnDisconnect(true);
    BLEService* service = server->createService(SERVICE_UUID);
    service->createCharacteristic(COMMAND_UUID, BLECharacteristic::PROPERTY_WRITE)->setCallbacks(&commandCallbacks);
    state = service->createCharacteristic(STATE_UUID, BLECharacteristic::PROPERTY_READ);
    publishState();
    service->start();

    BLEAdvertising* advertising = BLEDevice::getAdvertising();
    BLEAdvertisementData advertisement;
    advertisement.setFlags(0x06);
    advertisement.setCompleteServices(BLEUUID(SERVICE_UUID));
    advertising->setAdvertisementData(advertisement);
    BLEAdvertisementData scanResponse;
    scanResponse.setName(name);
    advertising->setScanResponseData(scanResponse);
    advertising->setScanResponse(true);
    advertising->start();
    Serial.printf("[strider] BLE ready: %s\n", name);
}

void loop() {
    M5StackChan.update();

    portENTER_CRITICAL(&mailboxLock);
    const bool connectionEnded = disconnected;
    const bool received = hasCommand;
    const Command command = pending;
    const uint32_t commandAt = pendingAt;
    disconnected = false;
    hasCommand = false;
    portEXIT_CRITICAL(&mailboxLock);

    const uint32_t now = millis();
    if (received && now - commandAt < COMMAND_TIMEOUT_MS) {
        lastCommandAt = commandAt;
        applyCommand(command, now);
        publishState();
    }

    if ((active.direction || driveOutput) && (connectionEnded || now - lastCommandAt >= COMMAND_TIMEOUT_MS)) {
        active.direction = 0;
        brakeFrom = 0;
        reactionUntil = now;
        lastAnimationAt = now - ANIMATION_INTERVAL_MS;
        setDriveOutput(0);
        publishState();
    }
    updateBraking(now);
    updateAnimation(now);

    static uint32_t lastStateAt = 0;
    if (now - lastStateAt >= 5000) {
        lastStateAt = now;
        publishState();
    }
    delay(5);
}
