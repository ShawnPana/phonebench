"""Track definitions — a track is a device class behind a backend.

One task suite, several tracks; results are labeled by track and never
blended. Each track resolves to the environment that pins phone-harness to
the right phone. Parallelism is per-track: iOS Mirroring is a single window,
adb devices are one agent per serial.
"""

TRACKS = {
    "real-ios": {
        "platform": "ios",
        "env": {},                      # the one Mirroring window; nothing to pin
        "parallel": 1,
        "description": "real iPhone via iPhone Mirroring — phonebench-real",
    },
    "real-android": {
        "platform": "android",
        "env": {"PHONE_HARNESS_PLATFORM": "android"},
        "parallel": 1,                  # one real phone
        "description": "real Android over adb — phonebench-real",
    },
    "emulate": {
        "platform": "android",
        "env": {"PHONE_HARNESS_PLATFORM": "android"},  # + ANDROID_SERIAL per device
        "parallel": 4,
        "description": "Android emulators (AVDs) — phonebench-emulate",
    },
    "appium": {
        # Cloud iPhones through the XCUITest tree — rented from phone-cloud
        # (api.phone-harness.com), the same surface any customer uses.
        # Caller must export: PATH with the cloud-capable phone-harness
        # first, PHONE_CLOUD_URL, PHONE_CLOUD_TOKEN (a user API key), and
        # PHONE_CLOUD_SESSION (from `phone-harness cloud up`). Sessions are
        # metered per-minute and idle out after 5 min — release promptly.
        "platform": "ios",              # checkers use the iOS branches
        "env": {"PHONE_HARNESS_PLATFORM": "cloud"},
        "parallel": 5,                  # the account's Device Farm ceiling
        "description": "cloud iPhone via phone-cloud (Device Farm, XCUITest tree) — phonebench-appium",
    },
}


def resolve(name, serial=None):
    track = dict(TRACKS[name])
    env = dict(track["env"])
    if serial:
        env["ANDROID_SERIAL"] = serial
    track["env"] = env
    return track
