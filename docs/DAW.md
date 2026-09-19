# Modo unificado (Pulse + JACK simultâneos) — SonusGrid

> Guia para uso em produção musical: Reaper, Ardour, Bitwig, Renoise, Mixbus,
> qualquer DAW que fale JACK. **Desde a v0.2.0, áudio do sistema (Spotify,
> Firefox, conferência) e o DAW funcionam ao mesmo tempo** — modelo
> SoundGrid: uma única "interface virtual" recebe todas as fontes e mistura
> por canal antes de enviar à rede Dante.

## Como funciona

```
   Spotify / Firefox → SonusGrid (Pulse sink)  →─┐
                                                  ├─► mix por canal ─► Dante
   Ableton / Reaper  → SonusGrid:tx_01..tx_16 ────┘  (canais 1+2 = sistema,
                       (cliente JACK)                 1-16 = DAW)
```

Tanto o sink PulseAudio (estéreo, para apps casuais) quanto as 16 portas
JACK (para DAW) são expostas pelo **mesmo processo** (`sonusgrid-bridge`),
que detém o handle único do `plug:sonusgrid` e mistura ambas as fontes antes
de mandar pra rede Dante. Não há "modo" pra trocar — sempre os dois ativos.

## Verificando

```bash
sonusgrid status
# audio service  : active
# PipeWire sink  : active     ← apps PulseAudio (Spotify) usam isto
# JACK client    : active     ← DAWs conectam aqui

pactl list sinks short | grep SonusGrid     # sink Pulse
pw-link -i | grep SonusGrid:tx              # 16 portas JACK in
pw-link -o | grep SonusGrid:rx              # 16 portas JACK out
```

## O que aparece no JACK

Quando o **Modo DAW** está ativo, o SonusGrid registra um cliente JACK chamado
`SonusGrid` com:

* **16 portas de entrada** (DAW → Dante): `SonusGrid:tx_01` … `SonusGrid:tx_16`
* **16 portas de saída** (Dante → DAW): `SonusGrid:rx_01` … `SonusGrid:rx_16`

Convenção: `tx_*` é o que o DAW *envia* (transmit) para a rede Dante;
`rx_*` é o que vem da rede Dante para dentro do DAW.

Verifique a presença com:

```bash
pw-link -i | grep SonusGrid    # 16 entradas
pw-link -o | grep SonusGrid    # 16 saídas
```

ou visualmente em **qpwgraph** / **qjackctl → Connect**.

## Configurando os DAWs

### Reaper

1. **Options → Preferences → Audio → Device**
2. **Audio system**: `JACK`
3. **Sample rate**: `48000` (deve bater com `sonusgrid status`)
4. **Request block size**: o mesmo número que você setou no SonusGrid GUI
   (ex.: `64`, `128`, `256`). Veja **⚠️ Reaper buffer caching** abaixo.
5. **Auto-start JACK if needed**: ☐ **DESMARCADO**
6. **Launch command**: **VAZIO** (deixa em branco)
7. **Routing**: insira tracks e em cada track escolha:
   * Input: `SonusGrid:rx_NN`
   * Master/Hardware out: `SonusGrid:tx_NN`

#### Por que "Auto-start JACK" fica desmarcado

Esse checkbox + launch command são vestígios da era **jackd2** quando você
precisava de um daemon `jackd` separado. Hoje no PipeWire:

* **PipeWire já é o servidor JACK** (sempre rodando como user service).
* Quando você abre o Reaper via `pw-jack reaper` (ou o atalho **REAPER (JACK
  / SonusGrid)** que o SonusGrid criou no menu), ele carrega a `libjack.so`
  do PipeWire que conecta direto — **sem precisar de auto-start**.
* Marcar o checkbox e botar um comando vai tentar spawnar um `jackd` real
  que **conflitaria** com o PipeWire.

**Recomendação**: sempre lança o Reaper via `pw-jack` ou pelo atalho do menu.

#### Caso excepcional — abrir Reaper sem `pw-jack`

Se você lançar `reaper` direto (sem `pw-jack`), o sistema carrega a libjack
do **jackd2** (que o `apt` instalou junto). Aí o Reaper realmente não acha
JACK e exibe erro. Nesse caso:

```
☑ Auto-start JACK if needed
Launch command:  pw-jack jack_lsp
```

`pw-jack jack_lsp` força o PipeWire-jack a se registrar (ele usa libjack do
PipeWire e lista os clients ativos — no-op útil que cria a conexão).

**Mas honestamente, só usa o atalho `pw-jack reaper` e ignora isso.**

### Ardour

1. Na startup dialog: **Audio System** = `JACK`, **Driver** = `alsa`
   (sob PipeWire, "alsa" é só o backend que o JACK-compat layer usa internamente).
2. **Sample rate** = 48000.
3. Crie tracks → em cada uma:
   * Input → `SonusGrid:rx_NN`
   * Output → `SonusGrid:tx_NN` (ou via Master Bus)

### Bitwig Studio

1. **Settings → Audio**
2. **Driver type**: `JACK`
3. **Inputs / Outputs**: marque os pares `SonusGrid:rx_NN` e `SonusGrid:tx_NN` que vai usar.
4. **Sample rate**: 48000.

### qpwgraph (visual / non-DAW)

Para roteamento manual (ex.: enviar um sintetizador standalone para Dante):

```bash
qpwgraph &
```

Arraste de qualquer porta de saída do seu app para `SonusGrid:tx_01/02`.
Arraste de `SonusGrid:rx_01/02` para a entrada do app.

## Latência

A unit JACK usa por default `--period 256` a 48 kHz, o que dá:

| Período (frames) | Latência por buffer | Round-trip total¹ | Recomendação                                |
| ---------------- | ------------------- | ----------------- | ------------------------------------------- |
| 64               | 1.3 ms              | ~4 ms             | Live monitoring com kernel RT               |
| 128              | 2.6 ms              | ~6 ms             | Recording de instrumentos sensíveis         |
| **256**          | **5.3 ms**          | **~12 ms**        | **Default — bom equilíbrio em kernel comum** |
| 512              | 10.6 ms             | ~22 ms            | Sessões grandes com muitos plugins          |
| 1024             | 21 ms               | ~43 ms            | Mixagem offline, sem monitoração ao vivo    |

¹ inclui hop ALSA→JACK→DAW→JACK→ALSA + ~1 ms de rede Dante.

### Trocando ao vivo (sem restart)

Pela GUI: **SonusGrid → Configuração → Buffer JACK**. A combo aplica
imediatamente via `pw-metadata`, sem precisar reiniciar nada. O áudio
continua tocando e a nova latência entra em vigor em milissegundos.

Equivalente no terminal:

```bash
pw-metadata -n settings 0 clock.force-quantum 64    # 1.3 ms @ 48k
pw-metadata -n settings 0 clock.force-quantum 0     # volta ao dinâmico
```

### ⚠️ Por que o Reaper continua mostrando o valor antigo

O Reaper **cacheia** o valor que **ele requisitou** ao abrir, não o que
o servidor JACK está realmente entregando. Se você setar o buffer no
SonusGrid GUI para 64 mas o Reaper ainda mostra 1024 nas preferências:

* O áudio do Reaper **JÁ ESTÁ rodando em 64 frames** — só a UI dele que
  mostra o número errado (limitação histórica do Reaper).
* Pra Reaper exibir o valor certo, faz uma das duas:
  1. Em **Reaper → Preferences → Audio → Device → Request block size**:
     digite `64` e Apply. Reaper agora pede e mostra 64.
  2. **OU** feche o Reaper, troca o buffer no SonusGrid GUI, reabre
     o Reaper — ele captura o valor atual no startup.

### Verificando o buffer real (truth-source)

```bash
pw-top                # coluna QUANT mostra o quantum em uso por nó
pw-metadata -n settings 0 clock.force-quantum    # valor forçado
pw-metadata -n settings 0 clock.quantum          # valor dinâmico
```

### Override permanente da unit

Para fixar o `--period` do bridge interno (separado do buffer JACK
do PipeWire) edite a unit:

```bash
systemctl --user edit sonusgrid-audio.service
```

```ini
[Service]
ExecStart=
ExecStart=/usr/bin/sonusgrid _internal-bridge-exec
# (período do bridge é fixado pelo cfg.bridge.relay_channels e --period 256
#  no audio.rs; pra mudar mexer no audio.rs e recompilar)
```

Reinicie:

```bash
systemctl --user restart sonusgrid-audio.service
```

## Kernel real-time (opcional, recomendado para período < 128)

Sem kernel RT, períodos abaixo de 128 produzem xruns audíveis sob carga.

### Ubuntu / Debian-based

```bash
sudo apt install linux-lowlatency
sudo reboot
uname -r    # deve conter "lowlatency"
```

### Fedora-based

```bash
sudo dnf install kernel-rt
```

### Permissões de RT scheduling

Crie `/etc/security/limits.d/99-audio.conf`:

```
@audio   -  rtprio     95
@audio   -  memlock    unlimited
@audio   -  nice       -19
```

Adicione seu usuário ao grupo:

```bash
sudo usermod -aG audio "$USER"
# logout e login novamente
```

A unit `sonusgrid-audio.service` já pede `LimitRTPRIO=95` e
`LimitMEMLOCK=infinity`, mas precisa que os limits do PAM permitam.

### Verificando

```bash
ulimit -r       # deve mostrar 95 ou superior
ulimit -l       # deve mostrar "unlimited"
chrt -p $(pgrep sonusgrid-bridge)   # mostra a SCHED policy do client
```

## Troubleshooting

### "Cannot connect to server socket — jackd is not running"

A libjack do **jackd2** está sendo carregada em vez do shim do PipeWire. Fix:

```bash
sudo apt install pipewire-jack
# Se preferir jackd2 explicitamente:
sudo update-alternatives --config jackd
```

A unit `sonusgrid-audio.service` força `LD_LIBRARY_PATH=/usr/lib/x86_64-linux-gnu/pipewire-0.3/jack`
no Debian/Ubuntu — em outras distros ajuste o caminho para a libjack do PipeWire.

### Cliente JACK não aparece

```bash
systemctl --user status sonusgrid-audio.service
journalctl --user -u sonusgrid-audio.service -n 100
```

Causas comuns:
* PipeWire não está rodando: `systemctl --user status pipewire`
* SonusGrid clock down: `systemctl --user start sonusgrid-clock.service`
* Outro processo segurando ALSA `plug:sonusgrid`: pare apps que estavam usando o sink Pulse antes.

### Xruns durante uso

```bash
journalctl --user -u sonusgrid-audio.service -f | grep -i xrun
```

Se xruns ocorrem mesmo em período 256 com kernel comum:
1. Verifique CPU governor: `cat /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor` deve ser `performance`.
2. Desative power-save Wi-Fi: `sudo iw dev wlan0 set power_save off`.
3. Use cabo Ethernet — Wi-Fi nunca dá garantia de jitter < 1 ms.
4. Aumente o período para 512.

### DAW sample rate ≠ 48000

O SonusGrid roda fixo no `sample_rate` do `~/.config/sonusgrid/config.toml` (default 48000).
DAW configurado em sample rate diferente vai produzir áudio acelerado/lento ou silêncio.
Mude **ambos** para o mesmo valor (96000 também é suportado, ajuste a config e reinicie).

## Sample rate alto (96 kHz, 192 kHz)

Para gravação em alta resolução:

```bash
sonusgrid config edit
```

Mude:

```toml
[device]
sample_rate = 96000
```

Salve, depois:

```bash
sonusgrid restart
```

A latência por período cai pela metade (256 frames @ 96 kHz = 2.6 ms), mas a
banda na rede Dante dobra. Verifique se seu switch suporta o tráfego adicional
(Dante a 96 kHz exige Gigabit confiável).

---

# Unified mode (Pulse + JACK simultaneous) — SonusGrid (English)

> Guide for music-production use: Reaper, Ardour, Bitwig, Renoise, Mixbus,
> any DAW that speaks JACK. **As of v0.2.1, system audio (Spotify, Firefox,
> conferencing) and the DAW work at the same time** — SoundGrid model: a
> single "virtual interface" receives all sources and mixes them per-channel
> before sending to the Dante network.

## How it works

```
   Spotify / Firefox → SonusGrid (Pulse sink)  →─┐
                                                  ├─► per-channel mix ─► Dante
   Ableton / Reaper  → SonusGrid:tx_01..tx_16 ────┘  (channels 1+2 = system,
                       (JACK client)                  1-16 = DAW)
```

Both the PulseAudio sink (stereo, for casual apps) and the 16 JACK ports
(for DAW use) are exposed by the **same process** (`sonusgrid-bridge`),
which holds the single `plug:sonusgrid` handle and mixes both sources
before sending to the Dante network. There is no "mode" to switch — both
are always active.

## Verifying

```bash
sonusgrid status
# audio service  : active
# PipeWire sink  : active     ← PulseAudio apps (Spotify) target this
# JACK client    : active     ← DAWs connect here

pactl list sinks short | grep SonusGrid     # Pulse sink
pw-link -i | grep SonusGrid:tx              # 16 JACK in ports
pw-link -o | grep SonusGrid:rx              # 16 JACK out ports
```

## What appears in JACK

When **DAW mode** is active, SonusGrid registers a JACK client named
`SonusGrid` with:

* **16 input ports** (DAW → Dante): `SonusGrid:tx_01` … `SonusGrid:tx_16`
* **16 output ports** (Dante → DAW): `SonusGrid:rx_01` … `SonusGrid:rx_16`

Convention: `tx_*` is what the DAW *sends* (transmit) to the Dante network;
`rx_*` is what comes from Dante into the DAW.

Verify with:

```bash
pw-link -i | grep SonusGrid    # 16 inputs
pw-link -o | grep SonusGrid    # 16 outputs
```

or visually in **qpwgraph** / **qjackctl → Connect**.

## DAW configuration

### Reaper

1. **Options → Preferences → Audio → Device**
2. **Audio system**: `JACK`
3. **Sample rate**: `48000` (must match `sonusgrid status`)
4. **Request block size**: same value you set in the SonusGrid GUI
   (e.g., `64`, `128`, `256`). See **⚠️ Reaper buffer caching** below.
5. **Auto-start JACK if needed**: ☐ **UNCHECKED**
6. **Launch command**: **EMPTY** (leave blank)
7. **Routing**: insert tracks; on each track choose:
   * Input: `SonusGrid:rx_NN`
   * Master/Hardware out: `SonusGrid:tx_NN`

#### Why "Auto-start JACK" stays unchecked

That checkbox + launch command are leftovers from the **jackd2** era when
you needed a separate `jackd` daemon. Under PipeWire today:

* **PipeWire is the JACK server** (always running as a user service).
* Launching Reaper via `pw-jack reaper` (or the **REAPER (JACK /
  SonusGrid)** menu shortcut) loads PipeWire's `libjack.so` which connects
  directly — no auto-start needed.
* Checking the box and adding a command would try to spawn a real `jackd`
  which would **conflict** with PipeWire.

**Recommendation**: always launch Reaper through `pw-jack` or the menu
shortcut.

#### Edge case — running `reaper` without `pw-jack`

If you run plain `reaper` (no wrapper), the system loads jackd2's libjack
which then can't find a `jackd` daemon. You can work around it with:

```
☑ Auto-start JACK if needed
Launch command:  pw-jack jack_lsp
```

`pw-jack jack_lsp` forces PipeWire-jack to register (it uses PipeWire's
libjack and lists clients — a useful no-op that creates the connection).

**But honestly, just use the `pw-jack reaper` shortcut and ignore this.**

### Ardour

1. In the startup dialog: **Audio System** = `JACK`, **Driver** = `alsa`.
2. **Sample rate** = 48000.
3. Create tracks → per track:
   * Input → `SonusGrid:rx_NN`
   * Output → `SonusGrid:tx_NN` (or via Master Bus)

### Bitwig Studio

1. **Settings → Audio**
2. **Driver type**: `JACK`
3. **Inputs / Outputs**: pick the `SonusGrid:rx_NN` and `SonusGrid:tx_NN`
   pairs you'll use.
4. **Sample rate**: 48000.

### qpwgraph (visual)

```bash
qpwgraph &
```

Drag from any app's output port to `SonusGrid:tx_01/02`. Drag from
`SonusGrid:rx_01/02` into the app's input.

## Latency

The JACK unit defaults to `--period 256` at 48 kHz, giving:

| Period (frames) | Per-buffer latency | Total round-trip¹ | Recommendation                                |
| --------------- | ------------------ | ----------------- | --------------------------------------------- |
| 64              | 1.3 ms             | ~4 ms             | Live monitoring with RT kernel                |
| 128             | 2.6 ms             | ~6 ms             | Recording sensitive instruments               |
| **256**         | **5.3 ms**         | **~12 ms**        | **Default — good balance on stock kernel**    |
| 512             | 10.6 ms            | ~22 ms            | Large sessions with many plug-ins             |
| 1024            | 21 ms              | ~43 ms            | Offline mixing without live monitoring        |

¹ includes ALSA→JACK→DAW→JACK→ALSA hop + ~1 ms Dante network.

To change, edit the unit:

```bash
systemctl --user edit sonusgrid-audio.service
```

Add an override:

```ini
[Service]
ExecStart=
ExecStart=/usr/libexec/sonusgrid/sonusgrid-jack --client-name SonusGrid --alsa plug:sonusgrid --rate 48000 --channels 16 --period 128
```

Restart:

```bash
systemctl --user restart sonusgrid-audio.service
```

## Real-time kernel (optional, recommended for period < 128)

Without an RT kernel, periods below 128 produce audible xruns under load.

### Ubuntu / Debian-based

```bash
sudo apt install linux-lowlatency
sudo reboot
uname -r    # should contain "lowlatency"
```

### Fedora-based

```bash
sudo dnf install kernel-rt
```

### RT scheduling permissions

Create `/etc/security/limits.d/99-audio.conf`:

```
@audio   -  rtprio     95
@audio   -  memlock    unlimited
@audio   -  nice       -19
```

Add yourself to the group:

```bash
sudo usermod -aG audio "$USER"
# log out and back in
```

The `sonusgrid-audio.service` unit already requests `LimitRTPRIO=95` and
`LimitMEMLOCK=infinity`, but the PAM limits must allow it.

### Verifying

```bash
ulimit -r       # should be 95 or higher
ulimit -l       # should be "unlimited"
chrt -p $(pgrep sonusgrid-bridge)   # shows the client's SCHED policy
```

## Troubleshooting

### "Cannot connect to server socket — jackd is not running"

The **jackd2** libjack is being loaded instead of the PipeWire shim. Fix:

```bash
sudo apt install pipewire-jack
# Or, if you want jackd2 explicitly:
sudo update-alternatives --config jackd
```

The `sonusgrid-audio.service` unit forces
`LD_LIBRARY_PATH=/usr/lib/x86_64-linux-gnu/pipewire-0.3/jack` on Debian/Ubuntu —
adjust the path for other distros' PipeWire-jack location.

### JACK client doesn't appear

```bash
systemctl --user status sonusgrid-audio.service
journalctl --user -u sonusgrid-audio.service -n 100
```

Common causes:
* PipeWire isn't running: `systemctl --user status pipewire`
* SonusGrid clock is down: `systemctl --user start sonusgrid-clock.service`
* Another process holds ALSA `plug:sonusgrid`: stop apps that were using the
  Pulse sink first.

### Xruns during use

```bash
journalctl --user -u sonusgrid-audio.service -f | grep -i xrun
```

If xruns occur even at period 256 on a stock kernel:
1. CPU governor: `cat /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor`
   should be `performance`.
2. Disable Wi-Fi power save: `sudo iw dev wlan0 set power_save off`.
3. Use Ethernet — Wi-Fi never guarantees jitter < 1 ms.
4. Bump the period to 512.

### DAW sample rate ≠ 48000

SonusGrid runs at the fixed `sample_rate` from `~/.config/sonusgrid/config.toml`
(default 48000). A DAW set to a different sample rate will produce
sped-up/slowed-down audio or silence. Set **both** to the same value (96000
also supported — change config and restart).

## High sample rate (96 kHz, 192 kHz)

For high-resolution recording:

```bash
sonusgrid config edit
```

Change:

```toml
[device]
sample_rate = 96000
```

Save, then:

```bash
sonusgrid restart
```

Per-period latency halves (256 frames @ 96 kHz = 2.6 ms), but the Dante
network bandwidth doubles. Make sure your switch handles the additional
traffic (Dante at 96 kHz needs reliable Gigabit).
