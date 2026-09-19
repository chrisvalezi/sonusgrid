# Instalação — SonusGrid no macOS

> **Status:** Em desenvolvimento (fase A-G do plano `macos/`). O `.pkg` final
> ainda não está disponível para download — o usuário final terá esse fluxo
> quando a fase F (notarização) concluir. Esta página documenta como
> instalar uma vez que o `.pkg` exista, e como buildar do zero.

## Pré-requisitos físicos

- Mac com macOS 13 (Ventura) ou superior — Apple Silicon ou Intel.
- Switch gigabit (sem Wi-Fi para áudio Dante — Wi-Fi tem jitter incompatível
  com PTP).
- Pelo menos um equipamento Dante na rede.
- Cabo Ethernet conectando o Mac ao switch (use adaptador USB-C/Thunderbolt
  se o Mac não tiver porta de rede integrada).

## Caminho A — `.pkg` instalável (público)

```bash
chmod +x SonusGrid-0.3.0-universal.pkg   # nem sempre necessário
sudo installer -pkg SonusGrid-0.3.0-universal.pkg -target /
```

Ou clique duplo no Finder. O assistente de instalação:

1. Roda `preinstall` — remove versão anterior, dá `bootout` no launchd antigo.
2. Copia arquivos:
   - `/Applications/SonusGrid.app`
   - `/Library/Audio/Plug-Ins/HAL/SonusGrid.driver/`
   - `/Library/LaunchDaemons/io.sonusgrid.clock.plist`
   - `/usr/local/bin/sonusgrid`
   - `/usr/local/libexec/sonusgrid/statime-macos`
   - `/etc/sonusgrid/clock.toml` (default)
3. Roda `postinstall` — `launchctl bootstrap system` da plist do PTP,
   `launchctl kickstart` no `coreaudiod` para recarregar o HAL plugin.

Depois:

1. Abra **SonusGrid** no Launchpad.
2. Em **Configuração**, escolha a interface de rede que vai pro switch
   Dante (`en0  ·  192.168.0.151` por exemplo).
3. Clique **Aplicar** → **Iniciar**.
4. Em **Ajustes do Sistema → Som**, aparece **SonusGrid-Virtual** como
   saída e como entrada.
5. Roteie canais no Dante Controller (Windows ou Mac em outra máquina) —
   vai aparecer um device com o nome configurado (default
   `SonusGrid-Virtual`).

## Desinstalar

```bash
sudo launchctl bootout system /Library/LaunchDaemons/io.sonusgrid.clock.plist
sudo rm -rf /Library/Audio/Plug-Ins/HAL/SonusGrid.driver
sudo rm /Library/LaunchDaemons/io.sonusgrid.clock.plist
sudo rm /usr/local/bin/sonusgrid /usr/local/libexec/sonusgrid/statime-macos
sudo rm -rf /etc/sonusgrid /var/log/sonusgrid /var/run/sonusgrid
sudo rm -rf /Applications/SonusGrid.app
sudo killall coreaudiod
```

## Caminho B — Build do zero (desenvolvedores)

Pré-requisitos:

- Xcode 15+ (CLI tools no mínimo: `xcode-select --install`).
- Rust via rustup com targets `aarch64-apple-darwin` + `x86_64-apple-darwin`.
- Apple Developer Program ($99/ano) se você quer signed/notarized.
  - Cert `Developer ID Application` no chaveiro
  - Cert `Developer ID Installer` no chaveiro
  - `xcrun notarytool store-credentials AC_PASSWORD ...`
  - `export SONUSGRID_TEAM_ID=XXXXXXXXXX`

```bash
git clone https://github.com/chrisvalezi/sonusgrid
cd sonusgrid
git submodule update --init --recursive

# Crates Rust (universal binaries via cargo + lipo)
make build TARGET=aarch64-apple-darwin
make build TARGET=x86_64-apple-darwin

# HAL plugin + App SwiftUI
xcodebuild -project macos/halplugin/SonusGridHAL.xcodeproj -scheme SonusGridHAL ARCHS="arm64 x86_64"
xcodebuild -project macos/app/SonusGrid.xcodeproj -scheme SonusGrid ARCHS="arm64 x86_64"

# Bundle .pkg
bash macos/installer/build-pkg.sh 0.3.0 universal
```

Saída: `build/SonusGrid-0.3.0-universal.pkg` (signed + notarized).

## Sem `.pkg` notarizado: caminho de desenvolvimento

Útil para hackear sem comprar Apple Developer Program ($99/ano). **Não use
em produção** — o macOS bloqueia HAL plug-ins não-signed via Gatekeeper.

```bash
# Build com self-signed cert (não funciona pra Gatekeeper, mas funciona local)
xcodebuild ... CODE_SIGN_IDENTITY="-" CODE_SIGNING_REQUIRED=NO

# Instala manualmente
sudo cp -r macos/halplugin/build/Release/SonusGridHAL.bundle \
    /Library/Audio/Plug-Ins/HAL/SonusGrid.driver
sudo cp /usr/local/bin/sonusgrid /usr/local/libexec/sonusgrid/

# Permite plug-ins não-signed (PERIGOSO; reverta depois)
sudo spctl developer-mode enable-terminal
```

## Compatibilidade de versão macOS

| macOS | Status | Observação |
|---|---|---|
| 13 Ventura | ✓ Mínimo suportado | LSMinimumSystemVersion no Info.plist |
| 14 Sonoma  | ✓ | Mudanças de audio QoS testadas |
| 15 Sequoia | ✓ | Apple removeu kexts; HAL plug-in continua via `coreaudiod` |
| 16 Tahoe   | ✓ | Sem mudança de API relevante |
| 12 ou anterior | ✗ | SwiftUI mais recente exige API Ventura+ |

---

*Compatible with Dante audio networks; not affiliated with Audinate Pty Ltd.*
