# Cognitive Nexus Android Client (`android/`)

Native Android Studio project (Kotlin + Compose + MVVM + Hilt) that integrates with the additive `mobile_api/` backend.

## Prerequisites
- Android Studio (recent stable)
- Android SDK 35
- JDK 17
- Running `mobile_api` server

## Build and test
From repository root:

```bash
cd android
./gradlew :app:assembleDebug
./gradlew :app:testDebugUnitTest
./gradlew :app:connectedDebugAndroidTest
```

If `gradlew` wrapper files are missing in your environment, open `android/` directly in Android Studio and run Gradle tasks from IDE.

## Emulator setup
- Default backend URL in app build config: `http://10.0.2.2:8001/`
- `10.0.2.2` is required for Android emulator-to-host communication.
- Do **not** use `localhost` for host-machine backend from Android emulator.

## Physical device setup
- Use your development machine LAN IP, e.g. `http://192.168.1.20:8001/`
- Device and computer must be on same network.
- Backend URL is configurable in Settings and persisted via DataStore.

## Start backend API
From repository root:

```bash
uvicorn mobile_api.main:app --host 0.0.0.0 --port 8001 --reload
```

## Networking/security notes
- Development cleartext HTTP is enabled in this scaffold via `android:usesCleartextTraffic=\"true\"` for local/LAN testing.
- Production deployment must use HTTPS and authenticated backend exposure.
- Before production release, disable cleartext traffic and enforce HTTPS-only network security config.
- Provider keys remain on backend only; Android app never stores OpenAI/Anthropic/Gemini credentials.

## Troubleshooting
- Connection errors: verify backend URL and that the mobile API is running.
- Empty/partial feature results: backend may report unavailable provider/model/services; app surfaces backend state instead of fabricating data.
- If image/research/provider operations fail, check backend `/api/v1/health` and `/api/v1/providers` responses.
