# Troubleshooting — SonusGrid

Comece sempre por:

```bash
sonusgrid doctor        # diagnóstico completo, bilíngue
sonusgrid status        # estado dos serviços
sonusgrid logs -f       # log ao vivo (Ctrl+C para sair)
```

Cada mensagem do `doctor` tem uma seção abaixo — use Ctrl+F com a frase exata.

## Não liga / "falhou ao iniciar"

Desde a 0.2.1 o `sonusgrid start` **valida a configuração, limpa o estado *failed* do
systemd, inicia e verifica** os dois serviços. Se algo falhar ele imprime as últimas linhas do
log e sai com erro. As causas mais comuns:

| Sintoma no log | Causa | Solução |
|---|---|---|
| `network.interface is empty` | interface não escolhida | GUI → Configuração → Interface de rede → Aplicar |
| `Interface 'X' does not exist` | nome errado / placa removida | `ip -br addr` e corrija em `sonusgrid config edit` |
| `waiting for enpXsY to get an IPv4 address…` por muito tempo | cabo solto, DHCP lento | plugue o cabo; o serviço espera até 45 s e continua tentando a cada 3 s |
| `failed to create usrvclock server: Permission denied` (só ≤ 0.2.0) | `/tmp` sem permissão | atualize para ≥ 0.2.1 (sockets agora ficam em `$XDG_RUNTIME_DIR/sonusgrid`) |
| `opening pulse Simple for record … Timeout` | PipeWire travado/degradado | `systemctl --user restart pipewire pipewire-pulse wireplumber` e `sonusgrid start` |
| `no clock available (timeout waiting for overlay update)` | ponte subiu antes do PTP travar | ≥ 0.2.1 espera o lock automaticamente; se persistir, não há *master* PTP na rede — veja abaixo |
| `Start request repeated too quickly` (só ≤ 0.2.0) | limite de restart do systemd | `systemctl --user reset-failed sonusgrid-clock sonusgrid-audio` (o `start` da 0.2.1 já faz isso) |

## "sonusgrid-clock.service está em estado 'failed'"

```bash
sonusgrid logs clock         # veja o motivo
sonusgrid start              # limpa o failed e tenta de novo
```

## "Não consegui consultar o systemd --user"

Você está num shell sem sessão de usuário (ex.: `sudo`, `su`, SSH sem logind). Rode os
comandos como o **seu** usuário, numa sessão gráfica ou SSH normal. Se estiver via `sudo -u`,
exporte `XDG_RUNTIME_DIR=/run/user/$(id -u)` e
`DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u)/bus`.

## "Config ausente em …"

```bash
sonusgrid config init
```

## "Nenhuma interface de rede selecionada" / "Interface X não encontrada" / "está DOWN"

```bash
ip -br addr             # veja o nome e o estado das placas
sonusgrid config edit   # [network] interface = "…"
```

Não use Wi-Fi. Não use `lo`, `docker0`, `veth*` nem bridges.

## "Não consigo escrever em /run/user/…/sonusgrid"

O diretório de runtime é criado pelo systemd para a sua sessão. Se não existe, você não tem
uma sessão logind (veja o item do systemd --user acima). Como último recurso o SonusGrid usa
`~/.cache/sonusgrid/run`.

## "Usuário não está no grupo 'audio'"

O relógio PTP de hardware (`/dev/ptp0`) é liberado ao grupo `audio` pela regra udev do
pacote. Adicione-se e relogue:

```bash
sudo usermod -aG audio $USER
```

Sem isso o Statime ainda funciona, usando relógio de software (menos preciso).

## "statime não tem cap_sys_time"

```bash
sudo setcap cap_sys_time,cap_net_bind_service,cap_net_admin+ep /usr/libexec/sonusgrid/statime
```

## "Plugin ALSA não encontrado" / "bridge ausente" / "statime não encontrado"

Instalação incompleta. `sudo apt install --reinstall ./sonusgrid_*.deb` ou `./install.sh`.

## "PipeWire @clock drop-in ausente"

```bash
sudo install -Dm644 systemd/sonusgrid-pipewire-clock.conf \
     /usr/lib/systemd/user/pipewire.service.d/sonusgrid-clock.conf
systemctl --user daemon-reload
```

(O `start` reinicia o PipeWire uma única vez para aplicar o drop-in.)

## "pactl info falhou"

PipeWire/pipewire-pulse não está rodando para o seu usuário:

```bash
systemctl --user status pipewire pipewire-pulse wireplumber
systemctl --user restart pipewire pipewire-pulse wireplumber
```

## "pipewire está usando N MB de RAM — parece degradado"

Vimos o `pipewire` chegar a 2,7 GB e 30 % de CPU parado, sem entregar áudio a nenhum
cliente. Reinicie a pilha (os apps perdem o áudio por ~1 s):

```bash
systemctl --user restart pipewire pipewire-pulse wireplumber
sonusgrid start
```

## "…/00-sonusgrid-pipewire-jack.conf ausente"

Sem ele, `libjack.so.0` resolve para o jackd2 e o cliente JACK do SonusGrid não aparece nas
DAWs (o áudio de sistema continua funcionando).

```bash
echo /usr/lib/x86_64-linux-gnu/pipewire-0.3/jack | sudo tee /etc/ld.so.conf.d/00-sonusgrid-pipewire-jack.conf
sudo ldconfig && sonusgrid restart
```

## NTP (`systemd-timesyncd`, `chronyd`) — precisa parar?

**Não.** O Statime roda em modo *virtual-system-clock*: o relógio PTP é uma camada sobre
`CLOCK_MONOTONIC_RAW` e o relógio do sistema nunca é alterado. Versões antigas do `doctor`
mandavam parar o NTP — isso era desnecessário.

## Não há master PTP na rede

Todo dispositivo Dante é um master PTP em potencial; se o único "dispositivo" for o SonusGrid,
o Statime vira master e o engine pode não receber relógio. Ligue pelo menos um equipamento
Dante real na rede.

## Áudio com glitches / xruns

PTP em kernel não-RT sofre sob carga.

1. Aumente a latência:
   ```toml
   [device]
   rx_latency_ns = 8_000_000      # 8 ms (padrão 4 ms)
   tx_latency_ns = 8_000_000
   ```
   `sonusgrid restart`.
2. Kernel low-latency: `sudo apt install linux-lowlatency` e reinicie.
3. Na GUI, aba *Ferramentas*, aumente o *buffer JACK* (quantum do PipeWire).

## SonusGrid não aparece no Dante Controller

1. `sonusgrid status` — os dois serviços `active` e o sink `active`.
2. `sonusgrid devices` (ou `avahi-browse -t -r _netaudio-cmc._udp`) — você deve se ver.
3. O PC do Dante Controller está na **mesma sub-rede** (`ip addr` aqui vs. lá)?
4. Firewall: `sudo ufw status`. Libere UDP 319, 320, 4440, 4444, 4455, 5353, 8700, 8800 e a
   faixa RTP alta. Com `ufw`: `sudo ufw allow in on enp3s0`.
5. Switch com IGMP snooping **sem querier** bloqueia multicast — habilite o querier ou desative
   o snooping.

## Audacity não abre o device "sonusgrid"

Audacity ≤ 3.5 não fala S32 multicanal. Use **`sonusgrid_stereo`** (mesmo device com downmix
para 2 canais) ou grave da fonte PipeWire **SonusGrid_RX**.

## O dispositivo reaparece com nome diferente

Mais de um processo está abrindo `plug:sonusgrid` (ex.: `arecord -D sonusgrid` fora do
serviço). O engine deriva o DEVICE_ID do processo. Deixe **só o `sonusgrid-audio.service`**
segurando o device e use JACK/PipeWire para consumir.

## Ver o tráfego na rede

```bash
sudo tcpdump -i enp3s0 -nn 'udp port 5353 or udp portrange 4440-4455 or udp port 8800'
```

---

*Compatible with Dante audio networks; not affiliated with Audinate Pty Ltd.*
