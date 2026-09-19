# Instalação — SonusGrid

## Pré-requisitos físicos

- Switch gigabit (não-gerenciado serve; se for gerenciado, habilite IGMP snooping **com querier**).
- Pelo menos um equipamento Dante na rede (mesa, conversor, outro PC com DVS…).
- **Placa Ethernet dedicada** na máquina Linux. **Wi-Fi não funciona** com Dante — o jitter
  destrói o áudio. Qualquer adaptador USB-Ethernet resolve.
- Um PC Windows/macOS com **Dante Controller** na mesma sub-rede, para rotear canais.

## Pré-requisitos de software

- PipeWire ≥ 0.3.65 com `pipewire-pulse` e `pipewire-jack` (padrão em Ubuntu 22.10+,
  Fedora 35+, Arch). Em distros mais antigas: `sudo apt install pipewire pipewire-pulse pipewire-jack`.
- systemd (os serviços são *user units*).
- Python 3.10+, GTK 4 e libadwaita para a GUI (instalados automaticamente).

## Caminho A — `install.sh` (recomendado)

```bash
git clone https://github.com/chrisvalezi/sonusgrid.git
cd sonusgrid
./install.sh
```

Rode como seu usuário normal (o script chama `sudo` só quando precisa). Ele:

1. Detecta a distro e instala as dependências.
2. **Debian/Ubuntu/Mint**: usa `dist/sonusgrid_<versão>_<arch>.deb` se existir; senão compila
   um (`make deb`) e instala com `apt`. O *postinst* do pacote cuida de:
   `setcap` no Statime, regra udev para `/dev/ptp*`, `ld.so.conf.d` apontando `libjack` para o
   PipeWire-JACK, cache de ícones.
   **Fedora/Arch/openSUSE**: compila (`make build`), instala em `/usr` e faz os mesmos passos
   de sistema manualmente.
3. Adiciona você ao grupo `audio` (necessário para o relógio PTP de hardware, `/dev/ptp0`).
4. Cria `~/.config/sonusgrid/config.toml` e roda `sonusgrid doctor`.

Opções: `--build` (força compilar), `--deb arquivo.deb`, `--no-start`.

## Caminho B — `.deb` pronto

Baixe o pacote da página de *Releases* e:

```bash
sudo apt install ./sonusgrid_0.2.1-1_amd64.deb      # ou _arm64.deb
sudo usermod -aG audio $USER && newgrp audio        # ou faça logout/login
sonusgrid doctor
```

| Arquivo | Plataformas |
|---|---|
| `sonusgrid_<v>_amd64.deb` | PCs Intel/AMD 64-bit |
| `sonusgrid_<v>_arm64.deb` | Raspberry Pi 4/5 (OS 64-bit), Ubuntu Server arm64, ODROID… |

## Primeira configuração

A **interface de rede é obrigatória** — não existe "auto", justamente para nunca ligar em
Wi-Fi por acidente.

- **GUI**: menu de aplicativos → SonusGrid → aba **Configuração** → **Interface de rede**
  (lista cada placa com o IP atual) → **Aplicar**.
- **Terminal**:
  ```bash
  sonusgrid config edit
  ```
  ```toml
  [network]
  interface = "enp3s0"      # placa ligada ao switch Dante
  ```

Depois:

```bash
sonusgrid doctor     # tudo verde?
sonusgrid start      # ou botão Iniciar na GUI
sonusgrid status
```

O primeiro `start` habilita os serviços `sonusgrid-clock.service` e `sonusgrid-audio.service`
na sua sessão — a partir daí eles sobem sozinhos no login.

## Desinstalar

```bash
./uninstall.sh              # remove o pacote/arquivos, mantém ~/.config/sonusgrid
./uninstall.sh --purge      # remove também a configuração
```

Ou, só com apt: `sudo apt remove sonusgrid` (`purge` para apagar drop-ins).

---

## Compilando do fonte

Dependências de build (Debian/Ubuntu):

```bash
sudo apt install build-essential pkg-config libasound2-dev libpulse-dev \
     libjack-jackd2-dev python3 devscripts debhelper
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh      # Rust ≥ 1.75
```

```bash
make build            # statime + engine + cli + bridge + gui
make test             # cargo test + tests/smoke/cli.sh
make deb              # dist/sonusgrid_<v>-1_amd64.deb
sudo make install     # alternativa ao .deb (PREFIX=/usr por padrão)
```

Se instalar com `make install` (sem o `.deb`), rode também os passos de sistema que o
*postinst* faria — o `install.sh` faz isso por você em distros não-Debian:

```bash
sudo setcap cap_sys_time,cap_net_bind_service,cap_net_admin+ep /usr/libexec/sonusgrid/statime
echo /usr/lib/x86_64-linux-gnu/pipewire-0.3/jack | sudo tee /etc/ld.so.conf.d/00-sonusgrid-pipewire-jack.conf
sudo ldconfig
sudo udevadm control --reload-rules && sudo udevadm trigger /dev/ptp*
```

### Cross-compile para ARM64

Precisa de Docker + [cross](https://github.com/cross-rs/cross):

```bash
sudo apt install docker.io binutils-aarch64-linux-gnu qemu-user-static
cargo install cross
sudo usermod -aG docker $USER        # relogar depois
make deb-arm64                       # dist/sonusgrid_<v>-1_arm64.deb
```

### AppImage (experimental)

```bash
make appimage        # build/SonusGrid-x86_64.AppImage
```

O AppImage precisa conceder `cap_sys_time` ao Statime na primeira execução (pede senha via
`pkexec`). É menos testado que o `.deb`; prefira o pacote quando possível.

---

*Compatible with Dante audio networks; not affiliated with Audinate Pty Ltd.*
