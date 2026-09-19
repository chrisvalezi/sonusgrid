# FAQ — SonusGrid

## Isso é legal?

Reverse engineering for interoperability é legal sob a maioria das jurisdições:
- **Estados Unidos**: DMCA §1201(f) permite engenharia reversa para interoperabilidade.
- **União Europeia**: Diretiva 2009/24/EC art. 6 permite descompilação para interoperabilidade.
- **Brasil**: Lei do Software (9.609/98) art. 6º permite engenharia reversa para fins de compatibilidade.

O SonusGrid implementa o protocolo Dante de forma independente, baseado em projetos open source (o engine é um fork do [Inferno](https://github.com/teodly/inferno); o relógio PTP é um fork do [Statime](https://github.com/pendulum-project/statime)) e em captura de pacotes da rede. Não há cópia de código proprietário da Audinate.

## Vocês podem chamar isso de "Dante para Linux"?

Não. "Dante" é marca registrada da Audinate Pty Ltd. Por isso o produto se chama **SonusGrid**. A marca Audinate só aparece em texto descritivo ("compatible with Dante audio networks") — uso permitido sob doutrinas de fair use / uso descritivo da marca.

## Por que GPL? Posso usar isso na minha empresa?

Sim, pode. GPLv3 não impede uso comercial. **Distribuição** de versões modificadas é que precisa publicar o código.

A licença GPLv3 vem do Inferno (do qual o engine do SonusGrid é fork). Não é escolha do SonusGrid — é amarração técnica.

Se você só usa internamente (instalou e usa), pode fazer o que quiser. Se você modificar e **distribuir** (vender, hospedar como serviço público), as modificações têm que ser GPLv3 também.

## O engine é um fork do Inferno?

Sim. `crates/sonusgrid-engine/` é um fork in-tree do Inferno (renomeado, com o plug-in ALSA `type sonusgrid`, caminho de relógio configurável e ajustes de estabilidade). O `vendor/statime/` é um fork do Statime com exportação de relógio virtual (`usrvclock`). Os créditos estão em `crates/sonusgrid-engine/NOTICE` e `COPYING.thirdparty`. Melhorias genéricas são enviadas de volta ao upstream quando fazem sentido.

## "Inferno" aparece em algum lugar visível para o usuário?

**Não.** O nome "Inferno" é só o nome da biblioteca Rust interna que faz o trabalho do protocolo Dante. No produto:

- **Dante Controller** mostra o nome configurado em `[device].name` no `~/.config/sonusgrid/config.toml` — padrão **`SonusGrid-Virtual`**.
- **Menu de aplicativos / GUI / .desktop**: tudo "SonusGrid".
- **Comandos no terminal**: `sonusgrid`, `sonusgrid-gtk`.
- **Pacote**: `sonusgrid_*.deb` ou `SonusGrid-x86_64.AppImage`.
- **Logs do systemd**: serviços chamados `sonusgrid-clock.service` e `sonusgrid-audio.service`.

A única menção a "inferno" seria nos logs detalhados (`sonusgrid logs -f`), porque algumas linhas vêm da biblioteca interna. Isso é equivalente a ver "kernel" em logs do dmesg — é a engine, não o produto.

## Por que então usamos Inferno em vez de escrever do zero?

**Porque escrever do zero levaria 6+ meses para um dev**, e Inferno já existe, é GPL, é mantido, e funciona. Reescrever envolveria:

- Engenharia reversa de protocolos Dante (ARC, CMC, DBC) — semanas.
- Implementar RTP TX/RX com timing PTP-correto — semanas.
- Implementar mDNS Dante-flavor (TXT records específicos) — dias.
- Estabilizar com vários fabricantes de hardware Dante — meses.

Inferno já fez tudo isso. SonusGrid é a **camada de produto** (CLI, GUI, instalador, integração com PipeWire/systemd), o engine (fork do Inferno) é a **camada de transporte**. Como Firefox usa SpiderMonkey (engine JS), VS Code usa Electron (engine browser), SonusGrid usa seu engine derivado do Inferno.

## Posso usar isso em produção (estúdio profissional)?

Pode, com cautela. A stack é alpha-mas-usável (segundo o Inferno). Limitações conhecidas:
- **Sem AES67** — só protocolo Dante puro (não interoperando com hardware AES67 fora do mundo Dante).
- **Sem Dante Domain Manager (DDM)** — você não autenticará no DDM.
- **Multicast RX** com bugs conhecidos.
- **PTP em kernel padrão** tem jitter mais alto que kernel RT — bom o suficiente para a maioria dos cenários de PA, broadcast, gravação. Para mixagem ao vivo crítica, considere kernel low-latency.

Recomendação: faça um teste de regressão de uma semana antes de depender em produção. Se fizer parte de cadeia crítica, mantenha o DVS oficial Windows como fallback.

## Funciona com rede secundária (redundância Primary/Secondary)?

Ainda não. O SonusGrid usa uma interface só e aparece na rede como device "só primária" — funciona
normalmente numa rede redundante, mas sem redundância para o PC. O que falta, o que bloqueia
(precisa de um device com duas portas para capturar o protocolo) e como ajudar estão em
[ROADMAP.md](ROADMAP.md). O Dante define exatamente duas redes; não existe "terceira".

## Funciona com Dante Via?

Sim, no nível de transporte de áudio (canais RX/TX aparecem na matriz). Funcionalidades específicas do Via (descobertas USB, "headphone routing") não estão implementadas.

## Funciona com hardware Dante de qual fabricante?

Inferno é testado com:
- Audinate AVIO (AES3, DAI2, DIOUSBC)
- Behringer X32, Wing-Rack
- Soundcraft Vi2000, Vi3000
- Allen & Heath SQ-5/6, Qu-5D
- Yamaha LS9 (com card Dante-MY16-AUD)
- Genelec 8000-series Smart IP
- Dante Controller @ Win/Mac

Se seu hardware não está na lista, é provável que funcione mesmo assim — abra um issue se não funcionar.

## E o sample rate? Funciona em 96 kHz? 192 kHz?

Sim para 44.1, 48, 88.2, 96 kHz. 192 kHz funciona mas pouco testado.

## Posso usar com PulseAudio em vez de PipeWire?

Não testado. PipeWire é o que vem por padrão em Ubuntu 22.10+ e Fedora 35+. Em distros mais velhas, instale PipeWire (`apt install pipewire pipewire-pulse`).

## Como contribuo?

```bash
git clone https://github.com/chrisvalezi/sonusgrid
cd sonusgrid
make build
make test
```

Issues e PRs em GitHub. Foco atual: estabilidade e cobertura de hardware.

## Como reporto um bug?

Abra issue em GitHub com:
1. Saída completa de `sonusgrid doctor`
2. Versão (`sonusgrid version`)
3. Distro (`lsb_release -a`)
4. Descrição do que esperava vs o que aconteceu

---

*Compatible with Dante audio networks; not affiliated with Audinate Pty Ltd.*
