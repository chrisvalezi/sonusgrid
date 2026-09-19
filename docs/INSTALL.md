# Instalação — SonusGrid

## Pré-requisitos físicos

- Switch gigabit (não-gerenciado serve; se for gerenciado, habilite IGMP snooping **com querier**).
- Pelo menos um equipamento Dante na rede (mesa, conversor, outro PC com DVS…).
- **Placa Ethernet dedicada** na máquina Linux. **Wi-Fi não funciona** com Dante — o jitter
  destrói o áudio. Qualquer adaptador USB-Ethernet resolve.
- Um PC Windows/macOS com **Dante Controller** na mesma sub-rede, para rotear canais.

## Pré-requisitos de software

- **Ubuntu 24.04+, Debian 12+ (13 para a GUI), Linux Mint 22+, Fedora 40+, Arch.**
  Ubuntu 22.04 **não** serve: seu PipeWire (0.3.48) é anterior ao mínimo (0.3.65).
- PipeWire com `pipewire-pulse`, `pipewire-jack` e WirePlumber (padrão nessas distros).
- systemd (os serviços são *user units*).
- GUI: Python 3.11+, GTK 4.12+, libadwaita 1.5+ (instalados automaticamente).

## Caminho A — um comando (Debian / Ubuntu / Mint) — recomendado

```bash
curl -fsSL https://github.com/chrisvalezi/sonusgrid/releases/latest/download/install.sh | bash
```

O script baixa `SHA256SUMS` e o instalador `.run` da última *release* para a sua arquitetura,
confere o SHA-256 e o executa. Opções são repassadas: `… | bash -s -- --no-launch`,
`… | bash -s -- --uninstall`. `SONUSGRID_VERSION=v0.3.0 curl … | bash` fixa uma versão.

## Caminho B — instalador `.run`

Baixe `SonusGrid-<versão>-amd64.run` (ou `-arm64.run`) em
[Releases](https://github.com/chrisvalezi/sonusgrid/releases).

```bash
chmod +x SonusGrid-*.run
./SonusGrid-*.run
```

O instalador (rode como seu usuário, não com `sudo`):

1. Confere distro e arquitetura.
2. Pede a senha **uma vez** e instala o `.deb` + `pipewire-jack`, `wireplumber`, `pavucontrol`
   com `apt` (o *postinst* do pacote faz `setcap` no Statime, regra udev para `/dev/ptp*`,
   `ld.so.conf.d` para o PipeWire-JACK).
3. Adiciona você ao grupo `audio` (faça logout/login depois — relógio PTP de hardware).
4. Cria `~/.config/sonusgrid/config.toml`, roda `sonusgrid doctor` e oferece abrir a GUI.

Opções: `./SonusGrid-*.run -- --yes --no-launch`, `-- --deb-only`, `-- --uninstall [--purge]`;
`--check` verifica a integridade, `--noexec --target pasta` só extrai.

Duplo clique: funciona no Nemo (Mint), Dolphin (KDE) e Thunar (Xfce) — eles abrem um terminal.
O **GNOME Files (43+) não executa scripts**; no GNOME use o terminal ou o Caminho A.

### Verificando o download

```bash
sha256sum -c --ignore-missing SHA256SUMS      # SHA256SUMS está na mesma página de Releases
```

## Caminho C — `.deb` direto

```bash
sudo apt install ./sonusgrid_<versão>-1_amd64.deb pipewire-jack
sudo usermod -aG audio $USER                    # depois logout/login
sonusgrid doctor
```

| Arquivo | Plataformas |
|---|---|
| `sonusgrid_<v>-1_amd64.deb` | PCs Intel/AMD 64-bit |
| `sonusgrid_<v>-1_arm64.deb` | Raspberry Pi 4/5 (OS 64-bit bookworm), Ubuntu arm64, ODROID… |

## Caminho D — `install.sh` do repositório (Fedora / Arch / openSUSE / desenvolvimento)

```bash
git clone https://github.com/chrisvalezi/sonusgrid.git
cd sonusgrid
./install.sh            # detecta a distro, instala deps, compila (ou usa dist/*.deb) e instala
```

Em Debian/Ubuntu ele gera e instala um `.deb`; nas demais compila, faz `make install` em `/usr`
e executa os mesmos passos de sistema do *postinst*. Opções: `--build`, `--deb arquivo.deb`,
`--no-start`.

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
./SonusGrid-*.run -- --uninstall          # ou: curl … | bash -s -- --uninstall
./SonusGrid-*.run -- --uninstall --purge  # remove também ~/.config/sonusgrid
sudo apt remove sonusgrid                 # só o pacote
./uninstall.sh [--purge]                  # a partir do repositório
```

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
make deb              # dist/sonusgrid_<v>-1_<arch>.deb (arquitetura do host)
make run-installer    # dist/SonusGrid-<v>-<arch>.run
make release          # deb + run + dist/SHA256SUMS
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
