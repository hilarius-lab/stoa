# Separater ESP32-Geräteclient

Der Waveshare-ESP32-S3-ePaper-Client lebt vollständig unter
[`esp32-client/`](esp32-client/README.md). Der Ordner ist als eigenständiges
Übergabepaket konzipiert und enthält einen eingefrorenen, auf das Gerät
beschränkten OpenAPI-Teilvertrag. Android- und Backendimplementierung gehören
nicht zu diesem Teilprojekt.

Änderungen des Geräteclients erfolgen innerhalb dieses Ordners. Benötigte
Backendvertragsänderungen werden als Blocker beschrieben und separat versioniert.
