<p align="center">
  <img src="gui/sonus-gtk/data/icons/hicolor/scalable/apps/io.sonusgrid.SonusGrid.svg" width="96" alt="SonusGrid">
</p>

<h1 align="center">SonusGrid</h1>

<p align="center">
  <b>[PT]</b> Transforme um PC Linux em um dispositivo de áudio compatível com redes Dante.<br>
  <b>[EN]</b> Turn a Linux box into an audio endpoint that interoperates with Dante audio networks.
</p>

<p align="center">
  <a href="#instalação">Instalação</a> ·
  <a href="#uso-rápido">Uso rápido</a> ·
  <a href="docs/USER_GUIDE.md">Guia do usuário</a> ·
  <a href="docs/DAW.md">DAW / JACK</a> ·
  <a href="docs/TROUBLESHOOTING.md">Troubleshooting</a> ·
  <a href="#english">English</a>
</p>

---

> **Compatible with Dante audio networks; not affiliated with Audinate Pty Ltd.**
> "Dante" é marca registrada da Audinate. O nome aparece aqui apenas para descrever interoperabilidade.

## O que é

O SonusGrid faz o seu Linux aparecer no **Dante Controller** como um dispositivo com N canais de
entrada e N de saída (16 × 16 por padrão, até 256). Qualquer app do sistema — Spotify, Firefox,
OBS, Audacity — pode tocar e gravar da rede Dante; DAWs (Reaper, Ardour, Bitwig) enxergam um
cliente JACK multicanal de baixa latência.

Ele reúne, num único pacote:

| Componente | Função |
|---|---|
| **Statime** (Rust) | daemon PTP v1/v2 — sincroniza o relógio de mídia com a rede Dante |
| **SonusGrid Engine** (Rust, fork do [Inferno](https://github.com/teodly/inferno)) | plug-in ALSA que fala o protocolo Dante (ARC/CMC/DBC, RTP, mDNS) |
| **sonusgrid-bridge** (Rust) | ponte full-duplex PipeWire ↔ JACK ↔ ALSA em um só processo |
| **sonusgrid** (Rust) | CLI: `start`, `stop`, `status`, `doctor`, `logs`, `config` |
| **GUI** (GTK4 / libadwaita) | estado com lock PTP ao vivo, **mixer com faders e medidores**, dispositivos Dante na rede, configuração, diagnóstico e logs |

<!-- SCREENSHOT: tela principal (Status) da GUI -->
<p align="center">
  <img src="docs/images/status.png" width="720" alt="SonusGrid — tela de status">
</p>

## Requisitos

- **Linux x86-64 ou ARM64** com **PipeWire ≥ 0.3.65**, GTK 4.12+ e libadwaita 1.5+:
  Ubuntu 24.04+, Debian 12+ (13 para a GUI), Linux Mint 22+, Fedora 40+, Arch.
  *Ubuntu 22.04 não é suportado (PipeWire 0.3.48).*
- **Placa de rede Ethernet dedicada** ligada ao switch dos equipamentos Dante.
  **Wi-Fi não funciona** — Dante exige jitter < 1 ms.
- Um PC Windows/macOS com **Dante Controller** na mesma rede para rotear canais
  (a Audinate não distribui o Controller para Linux).
- Kernel low-latency é recomendado, não obrigatório (`sudo apt install linux-lowlatency`).

## Instalação

### 1. Um comando (Ubuntu / Debian / Mint) — recomendado

```bash
curl -fsSL https://github.com/chrisvalezi/sonusgrid/releases/latest/download/install.sh | bash
```

Baixa o instalador da última *release* para a sua arquitetura (amd64/arm64), confere o
SHA-256, instala o pacote e as dependências com `apt`, coloca você no grupo `audio` e
oferece abrir a GUI. Opções: `… | bash -s -- --no-launch`, `… | bash -s -- --uninstall`.

### 2. Instalador `.run` (duplo clique ou terminal)

Baixe `SonusGrid-<versão>-amd64.run` (ou `-arm64.run`) na página de
[Releases](https://github.com/chrisvalezi/sonusgrid/releases) e:

```bash
chmod +x SonusGrid-*.run && ./SonusGrid-*.run
```

(O navegador remove a permissão de execução: `chmod +x` ou *Propriedades → Permitir executar*.
Duplo clique funciona no Nemo, Dolphin e Thunar; o GNOME Files não executa scripts — use o terminal.)
Para remover: `./SonusGrid-*.run -- --uninstall`.

### 3. Pacote `.deb` direto

```bash
sudo apt install ./sonusgrid_<versão>-1_amd64.deb
sudo usermod -aG audio $USER        # depois faça logout/login
```

### 4. A partir do fonte (Fedora / Arch / openSUSE / desenvolvimento)

```bash
git clone https://github.com/chrisvalezi/sonusgrid.git && cd sonusgrid
./install.sh            # detecta a distro, instala deps, compila e instala
```

### Desinstalar

`./SonusGrid-*.run -- --uninstall`, `sudo apt remove sonusgrid`, ou `./uninstall.sh [--purge]` no repo.

Detalhes, verificação de downloads, cross-compile ARM64: [docs/INSTALL.md](docs/INSTALL.md).

## Uso rápido

1. **Escolha a interface de rede** ligada ao switch Dante.
   GUI: menu → **SonusGrid** → aba *Configuração* → *Interface de rede* → **Aplicar**.
   Terminal: `sonusgrid config edit` e preencha `[network] interface = "enp3s0"`.

2. **Inicie**:
   ```bash
   sonusgrid start
   ```
   ou clique em **Iniciar** na GUI. Em ~5–10 s o status fica verde
   (o serviço espera o relógio PTP travar antes de abrir o áudio).

3. **Roteie** no Dante Controller: o dispositivo `SonusGrid-Virtual` aparece na matriz com
   16 TX × 16 RX.

4. **Mande áudio**: em qualquer app escolha a saída **SonusGrid (Dante-compatible)**
   (`sonusgrid route` abre o pavucontrol já na aba certa). Para gravar da rede, a fonte
   **SonusGrid_RX** aparece como um microfone.

<!-- SCREENSHOT: Mixer -->
<p align="center">
  <img src="docs/images/mixer.png" width="720" alt="SonusGrid — mixer com faders e medidores">
</p>

<!-- SCREENSHOT: Rede Dante -->
<p align="center">
  <img src="docs/images/routing.png" width="720" alt="SonusGrid — dispositivos Dante na rede">
</p>

### Comandos do CLI

| Comando | O que faz |
|---|---|
| `sonusgrid start` / `stop` / `restart` | liga/desliga os dois serviços (relógio PTP + ponte de áudio) |
| `sonusgrid status [--json]` | estado dos serviços, sink PipeWire e cliente JACK |
| `sonusgrid mixer [show\|master <dB>\|mute on\|set tx\|rx <ch> <dB>\|meters]` | faders, mutes e medidores (mesmo controle da página Mixer) |
| `sonusgrid doctor` | diagnóstico completo, bilíngue — **rode isto antes de pedir ajuda** |
| `sonusgrid logs [clock\|audio] [-f]` | journal dos serviços |
| `sonusgrid config init\|show\|edit\|check` | gerencia `~/.config/sonusgrid/config.toml` |
| `sonusgrid devices` | dispositivos Dante visíveis via mDNS |
| `sonusgrid route` | abre o pavucontrol focado no SonusGrid |

Os serviços são **units de usuário do systemd** (`sonusgrid-clock.service`,
`sonusgrid-audio.service`) e são habilitados no primeiro `start` — depois disso sobem sozinhos
no login.

<!-- SCREENSHOT: aba Configuração -->
<p align="center">
  <img src="docs/images/config.png" width="720" alt="SonusGrid — configuração">
</p>

## Como funciona

```
 apps Pulse (Spotify, Firefox)        DAW via JACK (Reaper, Ardour)
        │  sink "SonusGrid"                 │  SonusGrid-JACK:tx_01..tx_16
        ▼                                   ▼
 ┌───────────────────── sonusgrid-bridge ─────────────────────┐
 │  mistura por canal  →  plug:sonusgrid (ALSA, full-duplex)  │
 │  captura            ←  canais 1+2 → fonte "SonusGrid_RX"   │
 │                        todos os canais → SonusGrid-JACK:rx_NN   │
 └────────────────────────────┬───────────────────────────────┘
                              │ plug-in ALSA "SonusGrid Engine"
                              │ RTP + mDNS + ARC/CMC     ◄── relógio via Statime (PTP)
                              ▼
                    switch + equipamentos Dante
```

Arquitetura interna, decisões e limites em [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
Funcionalidades futuras (redundância Primary/Secondary, failover de interface) em
[docs/ROADMAP.md](docs/ROADMAP.md).

## Problemas?

```bash
sonusgrid doctor        # diz exatamente o que está errado e como corrigir
sonusgrid logs -f       # log ao vivo dos dois serviços
```

Cada mensagem do `doctor` tem uma seção em [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md).
Ao abrir uma *issue*, cole a saída do `doctor`, `sonusgrid version` e `lsb_release -a`.

## Estrutura do repositório

```
crates/sonus-cli/         CLI `sonusgrid` (Rust)
crates/sonusgrid-bridge/  ponte PipeWire/JACK ↔ ALSA (Rust)
crates/sonusgrid-engine/  engine Dante — fork do Inferno (plug-in ALSA, mDNS, usrvclock)
crates/inferno-c/         binding C do engine (usado pelo plug-in HAL do macOS)
vendor/statime/           daemon PTP (fork do Statime com exportação de relógio virtual)
gui/sonus-gtk/            GUI GTK4/libadwaita (Python)
systemd/                  units de usuário + drop-in do PipeWire
packaging/debian/         pacote .deb (postinst faz setcap, udev, ld.so)
packaging/makeself/       instalador .run para usuário final (makeself vendorado)
packaging/bootstrap/      install.sh publicado na release (one-liner)
packaging/udev|appimage/  regra udev; AppImage (experimental)
.github/workflows/        CI (build + teste de instalação) e Release (deb+run amd64/arm64)
scripts/                  bump-version, check-version, changelog-section
macos/                    porte macOS (HAL plug-in + launchd) — experimental
docs/                     documentação PT-BR (+ docs/en/)
install.sh / uninstall.sh instalador de desenvolvedor (a partir do repo)
Makefile                  build, deb, run-installer, release, install
```

## Desenvolvimento

```bash
make build            # statime + engine + cli + bridge + gui   (~5 min na primeira vez)
make test             # testes unitários + smoke test do CLI
make deb              # dist/sonusgrid_<versão>-1_<arch>.deb
make run-installer    # dist/SonusGrid-<versão>-<arch>.run
make release          # deb + run + dist/SHA256SUMS
make install          # instala em /usr (PREFIX=... para mudar)
make bump VERSION=x.y.z   # atualiza todas as versões + changelog; depois: commit, tag vX.Y.Z, push
```

Um `git push` de tag `v*` dispara o workflow de release: compila `.deb` + `.run` para amd64 e
arm64 em `debian:bookworm`, gera `SHA256SUMS` e publica tudo na página de Releases.

Precisa de: Rust ≥ 1.75, `pkg-config`, `libasound2-dev`, `libpulse-dev`, `libjack-jackd2-dev`,
`devscripts debhelper` (para o `.deb`). O `install.sh --build` instala tudo isso.

## Autor

**Chris Valezi** — [@djchrisnobeat](https://github.com/chrisvalezi) · chrisvalezi@gmail.com
Repositório: https://github.com/chrisvalezi/sonusgrid

## Licença

**GPL-3.0-or-later** (herdada do Inferno). Veja [COPYING](COPYING) e
[COPYING.thirdparty](COPYING.thirdparty) para Statime (Apache-2.0/MIT) e demais dependências.

---

## English

**SonusGrid** turns a Linux machine into a Dante-compatible audio device: a PTP clock daemon
(Statime), an ALSA plug-in speaking the Dante protocol (SonusGrid Engine, a fork of Inferno),
a native PipeWire ↔ JACK ↔ ALSA bridge and a GTK4 GUI. Any Linux app can play to / record
from the Dante network; DAWs get a 16×16 (up to 256×256) JACK client.

```bash
git clone https://github.com/chrisvalezi/sonusgrid.git && cd sonusgrid
./install.sh                       # Debian/Ubuntu: .deb; others: build from source
sonusgrid config edit              # set [network].interface to the NIC on the Dante switch
sonusgrid start                    # or use the GUI
sonusgrid doctor                   # bilingual diagnostics
```

```bash
# or the one-liner (Debian/Ubuntu/Mint):
curl -fsSL https://github.com/chrisvalezi/sonusgrid/releases/latest/download/install.sh | bash
```

English docs: [Install](docs/en/INSTALL.md) · [User guide](docs/en/USER_GUIDE.md) ·
[Troubleshooting](docs/en/TROUBLESHOOTING.md) · [FAQ](docs/en/FAQ.md) ·
[Architecture](docs/ARCHITECTURE.md).

*Compatible with Dante audio networks; not affiliated with Audinate Pty Ltd.*
