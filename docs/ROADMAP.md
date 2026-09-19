# Roadmap — SonusGrid

Funcionalidades planejadas, com o que já se sabe sobre cada uma. Ordem ≈ prioridade.
Contribuições e capturas de pacotes são bem-vindas — veja o fim de cada item.

## 1. Redundância Dante (Primary + Secondary) — *future feature*

**O que é.** O Dante permite duas redes físicas totalmente separadas (Primary e Secondary).
Cada dispositivo com duas portas envia o mesmo áudio pelas duas ao mesmo tempo; o receptor usa o
que chegar primeiro. Se um cabo ou switch cai, o áudio continua sem falha. O protocolo define
**exatamente duas** redes — não existe terceira.

**Estado atual (0.3.x).** O SonusGrid usa uma única interface (`[network] interface`). Numa rede
redundante ele funciona normalmente como device "só primária" (igual a um AVIO ou às Genelec
Smart IP), sem redundância para o próprio PC.

**O que precisa ser feito.**

| Camada | Trabalho |
|---|---|
| Config | `[network] secondary_interface`, `secondary_bind_ip`; validação de que as duas sub-redes são diferentes |
| Statime (PTP) | segundo `[[port]]` no TOML gerado; um único relógio, BMCA por porta (Slave numa, Passive/Master na outra) |
| Engine (fork do Inferno) | hoje há **um** `self_info.ip_address` usado por ARC/CMC, mDNS, negociação de fluxos, TX e RX. É preciso: servidores ARC/CMC/flow-control nas duas interfaces; mDNS anunciando as duas (TXT records que o Dante Controller usa para mostrar Primary/Secondary); assinaturas negociadas por rede; TX duplicado; **RX com dedupe por número de sequência RTP** entre as duas redes |
| GUI | segundo seletor de interface; indicador de link/PTP por rede na página *Estado* |
| Doctor | checar que as duas interfaces estão em sub-redes distintas e não interligadas |

**Bloqueio.** A forma como um device redundante negocia assinaturas e anuncia as duas redes
**não é documentada** e o Inferno upstream não implementa. Só dá para descobrir capturando o
tráfego (mDNS, ARC, CMC) de um equipamento real com Primary+Secondary — mesa, stagebox ou DSP;
dispositivos Ultimo/AVIO e as Genelec têm uma porta só. Sem esse hardware na rede, não há como
testar, e o item fica parado.

**Como ajudar.** Se você tem um device redundante: `sudo tcpdump -i <nic> -w dante-primary.pcap
'udp port 5353 or udp portrange 4440-4455 or udp port 8700 or udp port 8800'` nas duas redes
enquanto assina um canal do device no Dante Controller, e abra uma *issue* com os dois `.pcap`.

## 2. Failover de interface (alternativa mais simples ao item 1)

Uma interface secundária configurada; se o link da primária cair (`operstate` DOWN ou sem IPv4),
o serviço troca de interface e reinicia o engine em ~2 s. Não é "sem costura" como a redundância
Dante, mas evita ficar sem som até alguém trocar um cabo. Testável sem hardware especial (basta
puxar o cabo). Candidato a 0.4.0.

## 3. Outros

- Suporte a AES67 fora do ecossistema Dante (SAP/SDP) — depende do engine.
- Multicast RX com mais robustez (bugs conhecidos herdados do upstream).
- Dante Domain Manager: não planejado (protocolo proprietário de autenticação).
- macOS: porte experimental existe em `macos/`; sem manutenção ativa.
