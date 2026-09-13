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
- Development cleartext HTTP is enabled only for debug builds via `android/app/src/debug/AndroidManifest.xml`.
- Production deployment must use HTTPS and authenticated backend exposure.
- Before production release, disable cleartext traffic and enforce HTTPS-only network security config.
- Provider keys remain on backend only; Android app never stores OpenAI/Anthropic/Gemini credentials.

## GitHub release workflow
Workflow: `.github/workflows/android-release.yml`

- Push to `main`: builds debug APK and uploads it as an Actions artifact.
- Push tag `v*` (example `v1.0.0`): attempts signed release APK + release AAB build, creates a GitHub Release, and attaches both binaries.
- If signing secrets are missing, workflow still publishes debug artifact and uploads a notice that signed release binaries were not published.

### Create first release tag
```bash
git checkout main
git pull
git tag v1.0.0
git push origin v1.0.0
```

## Install from GitHub on Android
Installable release claim is valid only after the workflow successfully creates a GitHub Release with APK attached.

1. Open repository **Releases** on your Android phone.
2. Open target version (for example `v1.0.0`).
3. Download APK asset (for example `cognitive-nexus-v1.0.0.apk`).
4. Install it.
5. If Android blocks install, allow installation from the source app (Chrome/Files) when prompted, then retry.

## Update installed app from later releases
- Download/install a newer APK from Releases with the same `applicationId`.
- Android performs an in-place update when signing is consistent.

## Troubleshooting
- Connection errors: verify backend URL and that the mobile API is running.
- Empty/partial feature results: backend may report unavailable provider/model/services; app surfaces backend state instead of fabricating data.
- If image/research/provider operations fail, check backend `/api/v1/health` and `/api/v1/providers` responses.
- Backend must be reachable for AI chat, research, image generation, and remote model operations to work.
