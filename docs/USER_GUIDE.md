# Guia do Usuário — SonusGrid

> **Para uso em DAW (produção musical, low-latency)** veja o guia dedicado
> [DAW.md](./DAW.md) — explica o cliente JACK embarcado, latência por
> período, kernel real-time e setup de Reaper / Ardour / Bitwig.

## Conceito em uma frase

O SonusGrid expõe seu PC Linux como um dispositivo Dante na rede. Você roteia
canais com o **Dante Controller** (rodando num Windows/Mac qualquer), e
qualquer app Linux que toque ou grave áudio (Spotify, Firefox, Audacity, DAW)
fala com a rede Dante.

## Fluxo de áudio (modelo unificado, estilo SoundGrid)

```
   apps Pulse           DAW JACK (Reaper, Ardour, Bitwig)
   (Spotify, Chrome,    │
    pavucontrol)        │ JACK ports SonusGrid-JACK:tx_01..tx_NN
        │               │
        │ PulseAudio    ▼
        ▼            ┌────────────────────────────────────┐
   PipeWire null-   │   sonusgrid-bridge (1 processo)    │
   sink "SonusGrid"│   • dono único do plug:sonusgrid   │
        │            │   • mistura PA + JACK por canal    │
        │ monitor    │   • exposes JACK rx_01..rx_NN      │
        ▼            └────────────────────────────────────┘
                                  │ ALSA s32le N canais
                                  ▼
                          [plug-in SonusGrid em Rust]
                                  │ RTP multicast/unicast
                                  ▼
                       [Switch + equipamentos Dante]
                                  ▼
                              🔊 som
```

A versão atual usa um **bridge nativo em Rust** (`sonusgrid-bridge`) que
substituiu a etapa antiga via ffmpeg, eliminando ~20 s de latência e
xruns periódicos. Não há mais dependência de ffmpeg em runtime.

## Operação dia-a-dia

### Iniciando

Dois caminhos equivalentes:
1. **GUI**: clica em **SonusGrid** no menu de aplicativos. Se o status for
   "Parado", clica em **Iniciar**.
2. **Terminal**: `sonusgrid start`

O `start` valida a configuração, sobe o relógio PTP, **espera ele travar**
(5–10 s normalmente) e só então abre o áudio. Se algo falhar, ele mostra as
últimas linhas do log. Depois do primeiro `start` os serviços ficam
habilitados e sobem sozinhos no login — para desligar isso:
`systemctl --user disable sonusgrid-clock.service sonusgrid-audio.service`.

Quando o status fica verde você verá o device "SonusGrid-Virtual" na matriz
do Dante Controller.

### Roteando canais

Você precisa do **Dante Controller** rodando em outro PC na mesma rede
(Windows ou macOS — Audinate não disponibiliza para Linux). Ele detecta seu
SonusGrid automaticamente e mostra na matriz com **N TX × N RX**, onde N é
o que você configurou em `device.tx_channels` / `rx_channels` (default 16,
suporta até 256).

Para verificar dispositivos Dante visíveis sem o Controller:

```bash
sonusgrid devices    # lista devices Dante visíveis na rede via mDNS
```

### Mandando áudio do Linux para o SonusGrid

**Pela GUI**: abra o SonusGrid → página **Rede Dante**. Ela lista os
dispositivos Dante descobertos na rede, o buffer JACK da sessão PipeWire e
os atalhos para o **mixer por aplicativo (pavucontrol)** — onde você escolhe
o SonusGrid como saída de cada app — e para o **patchbay visual (qpwgraph)**
para ligar portas JACK/PipeWire à mão.

**Pelo pavucontrol**:

```bash
sonusgrid route      # abre pavucontrol focado no playback
```

Na aba **Reprodução**, ao lado de cada app, clica no botão da saída e
escolhe **SonusGrid (Dante-compatible)**.

**Tudo do sistema**:
```bash
pactl set-default-sink SonusGrid
```
Reverta com `pactl set-default-sink <nome-anterior>` (descobre com
`pactl list short sinks`).

### Capturando áudio Dante para o Linux

O SonusGrid expõe **dois caminhos de captura**, dependendo do app:

* **Para apps PulseAudio** (Audacity, OBS, conferência) — a fonte virtual
  `SonusGrid_RX` (estéreo, canais 1+2) aparece em
  `pavucontrol → Gravação` como se fosse um microfone.

* **Para DAWs JACK** (Reaper, Ardour, Bitwig) — as portas
  `SonusGrid-JACK:rx_01..rx_NN` recebem áudio multicanal direto, sem o limite de
  2 canais. Veja [DAW.md](./DAW.md).

### Volume — o Mixer

Todo o volume do que vai para a rede Dante é controlado na página **Mixer** da GUI (ou por
`sonusgrid mixer`): um fader **MASTER** com mudo, e um fader por par de canais (1-2, 3-4…)
com mudo e *link* L/R — tanto para **Saída → Dante** quanto para **Entrada ← Dante**.

- Os medidores dos canais mostram o sinal **antes** do master; o medidor do MASTER mostra o
  que realmente sai. Atualizam na taxa da sua tela (60 fps num monitor de 60 Hz).
- Nunca há ganho acima de 0 dB. Os níveis são salvos em `~/.config/sonusgrid/mixer.toml` e
  voltam iguais no próximo start — nunca "sobem sozinhos".
- O sink PipeWire "SonusGrid" fica fixo em 100 %; se algum app o alterar, o `doctor` avisa e
  o próximo `sonusgrid restart` normaliza (o mixer preserva o nível real).
- Na primeira execução, o master herda o volume que o sink tinha — o som não muda um dB.

Com caixas amplificadas no máximo (Genelec, etc.), use o MASTER como seu controle de
segurança: comece baixo e suba devagar.

### Parando

```bash
sonusgrid stop
```

Ou na GUI: clica em **Parar**.

## Configuração

Arquivo: `~/.config/sonusgrid/config.toml`. Pela GUI a aba **Configuração**
cobre todos os campos comuns. Pelo terminal:

```bash
sonusgrid config edit
sonusgrid config check     # valida
sonusgrid restart          # aplica
```

### Mudando o nome que aparece no Dante Controller

```toml
[device]
name = "Estúdio A"
```

### Mudando sample rate

```toml
[device]
sample_rate = 96000     # ou 44100, 48000, 88200, 96000, 176400, 192000
```

⚠️ Toda a rede Dante tem que estar no mesmo sample rate. Confira no Dante
Controller (menu **Device > Device Config**).

### Mudando o número de canais (até 256)

Pela GUI ou config:

```toml
[device]
rx_channels = 64        # canais que apps Linux podem GRAVAR da rede
tx_channels = 64        # canais que apps Linux podem TOCAR pra rede

[bridge]
relay_channels = 64     # bridge ALSA — deve casar com tx_channels
```

⚠️ Reinicie depois (`sonusgrid restart`). Limite teórico do engine: 256
canais cada direção (32 flows Dante × 8 canais por flow).

### Selecionando NIC

A interface de rede é **obrigatória** — não há mais modo "auto". Pela GUI o
dropdown da aba **Configuração** lista todas as NICs UP com seu IPv4. Se
preferir editar à mão:

```toml
[network]
interface = "enp11s0"
bind_ip   = "192.168.0.151"
```

O `bind_ip` é **auto-resolvido** a cada `sonusgrid start` lendo o IP atual
da `interface`. Se o seu DHCP renovar e o IP mudar, o bridge usa o novo IP
sem você precisar fazer nada — não mais panic com "No such device".

### PTPv2 / AES67

Se o seu setup roda em modo AES67 (PTPv2):
```toml
[ptp]
version = "v2"
```

### Cliente JACK on/off

```toml
[bridge]
jack_enabled = true     # default: registra cliente JACK SonusGrid
                        # com tx_NN/rx_NN ports para DAWs
```

Coloque `false` se você só usa áudio de sistema (Spotify, conferência) e
quer um grafo PipeWire mais limpo. A GUI tem um switch dedicado.

## Casos comuns

### Gravar um ensaio direto da mesa Dante

1. `sonusgrid start`
2. No Dante Controller (Windows/macOS): roteia canais da mesa para
   `SonusGrid.RX1..RX16` (ou quantos você configurou).
3. No Linux:
   * **Audacity / OBS**: seleciona `SonusGrid_RX` como input → grava
     estéreo (canais 1+2).
   * **Reaper / Ardour**: configura JACK driver → conecta
     `SonusGrid-JACK:rx_01..N` → input das tracks. Multicanal completo.

### Tocar um arquivo MP3 nas Genelecs

Mais simples: abra o player favorito (mpv, VLC, Rhythmbox, Spotify) e
selecione **SonusGrid** como saída. O sink Pulse aceita qualquer formato e
samplerate via PipeWire.

```bash
mpv --audio-device=pulse/SonusGrid musica.mp3
# ou
pw-play musica.wav --target=SonusGrid
```

### Linux box como conversor Dante↔analógico permanente

1. Auto-start já vem habilitado depois do primeiro `sonusgrid start`. Para
   subir **sem ninguém logado**: `sudo loginctl enable-linger $USER`.
2. Default sink: `pactl set-default-sink SonusGrid`
3. Plugue uma interface USB de áudio na máquina e use o pavucontrol pra
   rotear o monitor do SonusGrid pra ela. Ou via qpwgraph.
4. Boota — SonusGrid sobe sozinho, áudio flui sem login gráfico.

## Audacity — caso especial

Audacity ≤ 3.5 não suporta multichannel ALSA via plug. Use o device
alternativo `sonusgrid_stereo` (downmix automático para 2 canais via dmix):

```
Audacity > Edit > Preferences > Audio Settings > Recording Device: sonusgrid_stereo
```

## Problemas?

Roda **`sonusgrid doctor`** primeiro. A saída é bilíngue PT/EN — cole no
fórum se precisar de ajuda.

Logs detalhados:
```bash
sonusgrid logs -f         # tail -f das duas units
sonusgrid logs clock      # só PTP
sonusgrid logs audio      # só bridge de áudio (Pulse + JACK + ALSA)
```

Pela GUI: página **Diagnóstico** → **Verificações** (o `doctor` como lista) e **Logs** (ao vivo, com filtro).

---

*Compatible with Dante audio networks; not affiliated with Audinate Pty Ltd.*
