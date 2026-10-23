# Kit 1.0: meno istruzioni, più loop

Proposta del 23 ottobre 2026, scritta dopo una ricerca su tre fronti:

- come lavora il team di Claude Code e quali funzioni sono ormai native;
- le prove misurate su quanto le istruzioni aiutano o peggiorano un agente;
- i loop e gli harness dei migliori ingegneri.

Il modello di riferimento è **Opus 5.5**. Le fonti sono in fondo. Quelle segnate *[sec.]* sono state lette solo tramite riassunti o mirror.

> **Stato: implementata in kit 1.0** (23 ottobre 2026), tutta in un passaggio invece che a fasi.
> Cosa è cambiato rispetto al testo qui sotto è nella sezione finale
> [Come è stata implementata](#come-è-stata-implementata).

---

## In breve

1. **Il kit è stato scritto per modelli più deboli di quello che usi ora.**
   - Anthropic ha tolto oltre l'80% del system prompt di Claude Code per i modelli Claude 5, senza perdite misurabili.
   - La guida per Opus 5 dice di togliere le istruzioni di verifica e di non usare subagent per ricontrollare il proprio lavoro: causano verifica eccessiva e spreco di token.
   - Il kit oggi chiede proprio questo: "send each result to `kit:verifier`".
2. **Quello che funziona è la pressione deterministica, non la prosa.** I test, il gate `check` dello Stop hook, il formatter dopo ogni modifica, `protect` e `guard` sono la parte migliore del kit. Restano tutti.
3. **"Parlare sempre a un loop" ora esiste in forma nativa.** *Claude Projects* (web, desktop, mobile) è una conversazione che coordina e apre un thread per ogni compito. Ha un pannello Overview (*Pronti per la review / Aspettano te / In corso*), notifiche e auto-fix delle PR. Il captain del kit diventa una versione snella da terminale, per il lavoro che deve girare sulla tua macchina.
4. **Metà del kit duplica funzioni native** arrivate nel 2026:
   - `/code-review` e `/simplify`;
   - `/goal` e `/loop` con ritmo auto-gestito;
   - `/autofix-pr`;
   - la vista agenti (`claude agents`);
   - il tool Workflow;
   - auto-compact con "Compact instructions";
   - `/doctor prompt-audit`.
5. **Le skill di dominio** (LLM e UI) vanno in plugin separati, attivi solo nei progetti che le usano. È la regola che il kit stesso scrive nel README §4.3.
6. **Prima di tagliare si misura.** I tuoi eval dicono già che il kit oggi fa poca differenza: Δ 0 su 2 casi su 3 già eseguiti. Si allarga la misura e si cancella ciò che non sposta il risultato.

Stima dell'effetto:
- token di istruzioni del kit, sommando il corpo di tutte le skill e gli agenti: da circa 29k a circa 9k;
- testo sempre caricato (descrizioni e iniezioni degli hook): da circa 1,7k token più promemoria periodici a circa 0,5k token.

---

## 1. Cosa dice la ricerca (le regole che ne seguono)

**R1. Ogni pezzo dell'harness è un'ipotesi su ciò che il modello non sa fare.** Per Anthropic queste ipotesi "invecchiano in fretta man mano che i modelli migliorano" ([harness design, mar 2026](https://www.anthropic.com/engineering/harness-design-long-running-apps)). Con Opus 4.6 hanno tolto la struttura a sprint, e i reset di contesto non servivano più già da Opus 4.5. Ben Mann: costruisci qualcosa che funzioni il 20-30% delle volte oggi, così funzionerà all'80% col modello successivo ([making of Claude Code](https://www.anthropic.com/engineering/making-of-claude-code)).
→ Ogni componente va ri-misurato a ogni nuovo modello e cancellato quando non serve più.

**R2. Opus 5 e 5.5 si verificano da soli.** Dalla [guida Opus 5](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-opus-5):
- istruzioni come "aggiungi un passo di verifica" o "usa un subagent per verificare" causano verifica eccessiva, e "removing them reduces wasted tokens with no loss in quality". Lo stesso vale per "legacy harness scaffolding";
- "do not use subagents to verify or double-check your own work";
- per i task non presidiati, limitare la delega.

La [guida Opus 5.5](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-opus-5-5) dice che i prompt per Opus 5 restano validi, e che la code review è ancora più forte, con più bug trovati e meno falsi allarmi.
→ Si tiene la verifica **esterna**: test, gate, una review a contesto pulito sul PR. Si tolgono le istruzioni di verifica.

**R3. Le regole generiche peggiorano i risultati, perché il modello le segue.**
- Un CLAUDE.md popolare di "linee guida" ha abbassato il pass rate da 53,7% a 51,5%. Il TDD imposto lo ha portato da 52,4% a 48,8%, con il 55% di costo in più ([programbench-bench](https://github.com/kunchenguid/programbench-bench); modello GPT-5.5, n=192).
- I file di contesto generati da un LLM danno −3%, quelli scritti a mano +4%, con oltre il 20% di costo in più ([Gloaguen et al., ICLR 2026](https://arxiv.org/abs/2602.11988)).
- Un'ablazione su Claude Code e Codex non trova nessun effetto misurabile di AGENTS.md sulla correttezza ([Khatri, lug 2026](https://arxiv.org/abs/2607.27250)) *[sec.]*.

→ Il testo sempre caricato contiene solo fatti che il modello non può dedurre: comandi, stranezze del repo, convenzioni non standard. Niente buoni comportamenti generici.

**R4. Hook al posto della prosa.** Dai [best practices di Claude Code](https://code.claude.com/docs/en/best-practices):
- "If Claude already does something correctly without the instruction, delete it or convert it to a hook";
- "if you emphasize many lines, none of them stands out".

Dall'articolo di Anthropic sullo [steering](https://claude.com/resources/articles/steering-claude-code-skills-hooks-rules-subagents-and-more): "A real guardrail needs to be deterministic".
→ Gli hook restano, ma silenziosi quando va tutto bene. Gli hook che *iniettano testo* vanno ridotti.

**R5. Un solo agente con le skill batte spesso i subagent.** "A single agent with skills frequently outperformed both the one-prompt-for-everything design and the subagent design" ([Anthropic, 22 ott 2026](https://claude.com/resources/articles/building-agents-when-to-fold-subagents-into-your-main-agent-loop)). I sistemi multi-agente costano circa 15 volte i token di una chat ([Anthropic, research system](https://www.anthropic.com/engineering/built-multi-agent-research-system)). Per Cognition funzionano quando c'è un solo agente che scrive e gli altri portano intelligenza (review, ricerca) *[sec.]*.
→ I subagent servono per isolare il contesto e per lavoro davvero parallelo, non come cerimonia per ogni compito.

**R6. La review indipendente paga al confine, non a ogni passo.** Separare chi lavora da chi giudica "è una leva forte" quando il compito supera ciò che il modello fa bene da solo ([harness design](https://www.anthropic.com/engineering/harness-design-long-running-apps)). Il reviewer di Cognition rende di più quando non condivide il contesto con chi ha scritto il codice *[sec.]*. Una review che cerca lacune "ne trova quasi sempre", e inseguirle tutte porta a sovra-ingegnerizzare (docs Claude Code).
→ Una review a contesto pulito per PR, solo per rischio medio o alto.

**R7. Il coordinatore ideale si sveglia sugli eventi e parla solo di eccezioni.** firstmate (Kun Chen), la vista agenti e Claude Projects convergono su:
- stato su disco;
- "Aspettano te" in cima;
- risultato più rischio in una riga;
- silenzio quando non cambia niente;
- decisioni in coda, ordinate per impatto.

**R8. L'umano sta ai due estremi.** Karpathy: "Don't tell it what to do, give it success criteria and watch it go" *[sec.]*. Horthy: rivedere ricerca e piano rende più che rivedere il codice. Ha anche visto una "dark factory" senza nessun umano degradare il codice in tre mesi *[sec.]*.
→ Restano `kit:shape` all'inizio e la PR giudicabile alla fine.

**R9. Un cricchetto con potatura.**
- Hashimoto e il team OpenAI di "harness engineering": ogni errore ricorrente diventa prima uno script, un lint o un tool, e solo dopo una riga di testo *[sec.]*.
- Kun Chen: il testo sempre caricato (file di memoria più tutte le descrizioni delle skill) va tenuto sotto circa 5k token, e quello che avanza va nelle skill ([blog](https://blog.kunchenguid.com/p/your-agentsmd-is-a-neural-net)).

**R10. Linguaggio calmo, il perché invece dell'ordine.** "CRITICAL: You MUST…" porta i modelli recenti a esagerare; "Tell Claude what to do instead of what not to do" ([prompting best practices](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices)). Per le skill vale "Claude is already very smart" e la domanda "does this paragraph justify its token cost?" ([skill authoring](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices)).

**R11. L'effort è la leva principale su Opus 5.5.**
- Il default è `medium`, che sul coding vale quanto `high` su Opus 5.
- `low` ci va vicino a costo molto più basso.
- `xhigh` e `max` vanno usati solo dove un guadagno è stato misurato.
- Per ridurre il ragionamento si abbassa l'effort; le frasi nel prompt funzionano peggio.

**R12. Nei run non presidiati Opus 5.5 a volte chiude il turno con un aggiornamento a metà lavoro.** La guida 5.5 consiglia di:
- trattarlo come un rapporto, non come fine del compito;
- tenere una checklist;
- rilanciare con "restano aperti X e Y", oppure far giudicare la condizione di fine a un modello più piccolo (è quello che fa `/goal`);
- fermarsi dopo 2-3 rilanci.

Offre anche un testo pronto da appendere al system prompt degli agenti autonomi.

---

## 2. Il kit oggi: cosa tenere e cosa pesa

| Componente | Verdetto | Perché |
|---|---|---|
| `stop_check` (gate `check` prima di fermarsi) | **tieni** | Pressione deterministica (R2, R4). Costa zero se non è cambiato nulla |
| `on_edit` (formatter e validatori) | **tieni** | È l'hook PostToolUse che usa Boris (R4) |
| `protect`, `guard` | **tieni** | Deterministici e silenziosi. Al cap sui subagent del guard preferisci le variabili native `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS` e `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH` |
| `.claude/kit.json` (`check`, `verify`, `protect`, `onEdit`) | **tieni** | Fatti di progetto che il modello non può dedurre (R3) |
| `kit:overnight` (`overnight.py`) | **tieni e migliora** | È gnhf, convergente con Ralph e Anthropic: contesto fresco, un commit per passo, gate, limiti. Aggiungi R12 |
| `/kit:learn` | **tieni e cambia direzione** | Il metodo backpass è giusto. Deve anche *togliere* righe e preferire hook o lint (R9) |
| `/kit:go` | **snellisci** (da 84 a ~30 righe) | Il `/go` di Boris ha tre passi: test end-to-end, `/simplify`, PR. Del tuo tieni intento, evidenza, rischio e babysit tramite `/autofix-pr` |
| `kit:shape` (skill) | **snellisci**, togli l'hook | Chiarire prima è utile (R8). Il riconoscimento con regex e l'iniezione a ogni prompt no |
| `kit:investigate` | **tieni e snellisci** | Valore unico: raccolta evidenze, `compact_logs.py`. Assorbe l'essenziale di systematic-debugging |
| `/kit:intake` + `CATALOG.md` | **tieni** (solo su richiesta) | È la tua governance, e ha funzionato |
| `kit:lead` + `captain.md` (235 righe) | **sostituisci** | Claude Projects nel cloud; in terminale un captain da circa 40 righe (§3) |
| `kit:verifier` per ogni compito | **sposta al confine** | Una review a contesto pulito per PR, rischio medio o alto (R2, R6) |
| `kit:implementer` | **tieni**, solo per il parallelo | Un worker in worktree con brief autosufficiente. Effort `medium` (R5, R11) |
| `kit:plan-reviewer` | **elimina** | Boris: dalla 4.6/4.7 "non serve un passo di pianificazione" *[sec.]*. Per una seconda opinione basta chiederla |
| `kit:code-simplifier`, `/kit:techdebt` | **elimina** | Nativo: `/simplify`. Le pulizie periodiche vanno in un loop (§4.2) |
| Workflow `/kit:review` (6 lenti × 2 scettici) | **elimina** | Nativo: `/code-review` (livelli di effort, `--fix`, `--comment`). Su Opus 5.5 la review è più forte. Le parti tue (intento, `review-decisions.md`, rischio) passano in `/kit:go` |
| Workflow `/kit:ship` | **elimina** | Il tool Workflow nativo scrive lo script al momento, e il captain fa lo stesso con i worker |
| `context_guard.py` + `compact.ts` (circa 260 righe) | **elimina** | Ti chiede la nota ogni 5 tool call: istruzioni a ripetizione. Al suo posto: auto-compact nativo, compattazione da inattività, "Compact instructions" in CLAUDE.md, skill ri-allegate dopo la compattazione, e per il captain una board su disco. Anche Amp è tornato alla compattazione automatica *[sec.]* |
| `shape_detect.py` | **elimina** | Regex più testo iniettato a ogni prompt. La descrizione della skill basta, e nel captain decide il captain |
| `verification-before-completion` (vendored) | **elimina** | Contraddice la guida Opus 5 (R2) |
| `systematic-debugging` (vendored, 283 righe + 4 file) | **elimina**, porta 10 righe in investigate | Doppione di `kit:investigate` |
| `llm-build`, `llm-evals`, `prompt-optimize`, `model-select`, `llm_detect` | **plugin `kit-llm`**, scope progetto | Dominio. La descrizione di llm-build da sola è lunga 919 caratteri. `prompt-optimize` e `model-select` diventano riferimenti di `llm-evals` |
| `ui`, `brand` | **plugin `kit-ui`**, scope progetto | Dominio. Aggiorna `ui` con la regola Opus 5.5: elencare gli stili precisi da evitare, non "evita il look generico" |
| Pannello (`panel.tsx`) | **tieni senza la modalità loop** | Stato e sicurezza utili. Il testo aggiunto a ogni prompt in modalità loop si sostituisce con il captain snello o con Projects |
| README (750 righe) | **riduci** a circa 150 più `docs/` | Non lo legge il modello, ma lo leggi tu |

Due cose superate da correggere comunque:

- `lead/SKILL.md` dice "Create a task list (TaskCreate)". Dalla 2.1.233 i tool Task non vengono offerti sui modelli recenti senza opt-in (`CLAUDE_CODE_ENABLE_TODO_TOOLS=1`).
- `auto mode` è già il default su Pro e Max dall'agosto 2026. `defaultMode: "auto"` nel settings di *progetto* viene ignorato.

---

## 3. "Parlare sempre a un loop": l'architettura proposta

```
                tu (testo o voce, terminale o telefono)
                         │
        ┌────────────────┴────────────────┐
        ▼                                 ▼
  CLAUDE PROJECTS (nativo)          CAPTAIN da terminale (kit)
  repo su GitHub, lavoro            lavoro che serve la tua macchina
  che può girare nel cloud          (dati locali, VPN, emulatori)
  - un thread per compito           - worker in background, worktree
  - Overview: pronti / aspettano te - board su disco, NEEDS YOU in cima
  - PR con auto-fix CI              - si sveglia su eventi (agenti, Monitor CI)
  - istruzioni + memoria progetto   - silenzio se non cambia niente
  - plugin kit nei thread           - /loop solo per watch esterni
        │                                 │
        └────────────────┬────────────────┘
                         ▼
     ogni worker: brief → lavoro → gate `verify` (deterministico)
     → PR con Intento / Evidenza / Corretto / Rischio
     → una review a contesto pulito se il rischio è medio o alto
```

**Opzione A: Claude Projects (consigliata dove il lavoro sta su GitHub)**

È esattamente il captain, già fatto, e in più ti segue sul telefono e manda notifiche. Il kit gli dà due cose:

1. **Le istruzioni di progetto**, circa 12 righe, che distillano `/kit:go`:

   ```
   - Target branch: main via PR. Never push to main.
   - Before opening a PR, run `<verify da kit.json>` and exercise the change the way a user
     meets it (run the CLI, load the page); attach the output or a screenshot.
   - PR body: Intent (what was asked and why), Evidence, Fixed along the way, Risk (low/medium/high and why).
   - Medium or high risk: run /code-review before asking me to merge.
   - Ask me only when different readings of a task would lead to materially different work.
   - Need my go-ahead: migrations, deploys, deleting data, anything outside the repo.
   ```

2. **Il plugin `kit`** in *Project settings > Plugins*, così i thread hanno skill e hook. Da verificare in prova: che gli hook dei plugin girino nei thread cloud (`check`, `protect`, `guard` richiedono `python3` nell'ambiente) e che `.claude/kit.json` venga letto dal repo.

Limiti da conoscere:
- È in beta su Pro e Max e non esiste in CLI.
- I thread cloud non leggono `.claude/settings.json`, le skill del repo, `.mcp.json` né gli hook del repo. Il plugin e i connettori invece sì.
- Per un compito che serve la tua macchina, puoi chiedere che "quel thread giri sul tuo computer" via Remote Control. In quel caso usa hook e impostazioni locali.

**Opzione B: captain da terminale (il kit)**

`lead` e `captain.md` diventano una sola skill `kit:captain` di circa 40 righe. Contiene solo quello che il modello non sa da solo:

- la board su disco (formato e percorso);
- la politica di consegna chiesta una volta;
- il gate di progetto come definizione di "fatto";
- il formato della risposta (al massimo 4 righe, NEEDS YOU prima, silenzio se non cambia niente);
- svegliarsi sugli eventi e non con polling;
- quando fermarsi;
- le azioni verso l'esterno solo con il tuo via libera.

Niente tabelle di meccanismi: Claude Code ha già le sue istruzioni sulla delega.

**Cosa non fare: `claude --agent kit:captain` come agente principale.** Il corpo di un agente usato come thread principale *sostituisce interamente* il system prompt di Claude Code, che Anthropic ottimizza per ogni modello ([sub-agents](https://code.claude.com/docs/en/sub-agents)). Si perderebbe proprio la parte più curata.

---

## 4. Proposte concrete

### 4.1 Togliere (ordinate per rapporto impatto/rischio)

1. **Le istruzioni di verifica.** Togli la skill `verification-before-completion`, la frase "Never accept an implementer's own done" e il verifier per ogni compito. Al loro posto: il gate dello Stop hook (c'è già), più una review a contesto pulito al PR per rischio medio o alto.
2. **Il richiamo del contesto** (`context_guard.py`, `compact.ts`, la reiniezione della nota). Tieni la sezione `# Compact instructions` in CLAUDE.md e `autoCompactWindow` come opzione.
3. **L'hook che riconosce i brain-dump.** `kit:shape` resta come skill e il captain lo usa quando serve.
4. **I doppioni dei nativi:** `/kit:review`, `/kit:ship`, `kit:code-simplifier`, `/kit:techdebt` e `kit:plan-reviewer`.
5. **Le skill di dominio dal plugin core:** passano a `kit-llm` e `kit-ui` nello stesso marketplace, con installazione `--scope project`.
6. **Il linguaggio da allarme.** Togli "Iron law", "MUST FIX", "Never…" in serie, e la frase "non stimare in giorni" ripetuta in tre file: resta solo nel tuo `~/.claude/CLAUDE.md`.
7. **Le skill usate solo su richiesta escono dal listing** con `disable-model-invocation: true`. Sono `intake` e `learn`, che si aggiungono a `go` e `init` già così: costo zero quando non le chiami.

### 4.2 Aggiungere (poco, e preferibilmente deterministico)

1. **Un test che "lintea" l'harness** (`plugins/kit/tests/test_budget.py`, solo stdlib). Fallisce se:
   - la somma delle descrizioni delle skill invocabili dal modello supera circa 2.000 caratteri;
   - una `SKILL.md` supera 150 righe (le guide dicono 500; per te è più stretto apposta);
   - compaiono `MUST`, `NEVER`, `CRITICAL` o `IMPORTANT` in maiuscolo fuori dai blocchi di codice;
   - un hook stampa testo quando tutto va bene.

   È il cricchetto di R9 applicato al kit stesso.
2. **L'effort per ruolo**, nel frontmatter degli agenti se il campo è supportato, altrimenti nel brief. Implementer `medium`, eventuale reviewer di default. `xhigh` solo dove un eval mostra il guadagno (R11).
3. **Una skill di verifica di progetto generata da `/kit:init`.** Si salva in `.claude/skills/e2e/SKILL.md`, circa 20 righe: come si avvia l'app, come la si esercita (CLI, pagina, API), cosa salvare come prova. È l'unico tipo di conoscenza che il modello non ha. Thariq Shihipar del team Claude Code dice che vale la pena dedicare una settimana a rendere eccellenti le skill di verifica *[sec.]*; Delba de Oliveira (Anthropic) concatena `/code-review`, `/simplify` e `/verify` ([verification loops](https://claude.com/resources/articles/building-verification-loops-in-claude-code-with-skills)).
4. **`overnight.py` adattato a Opus 5.5** (R12):
   - aggiunge il testo per agenti autonomi della guida 5.5 con `--append-system-prompt`;
   - tratta una chiusura con solo testo e lavoro aperto come rapporto, e rilancia una volta con l'elenco dei punti aperti (massimo 2 rilanci per iterazione);
   - accetta `--effort`.
5. **`/kit:learn` che pota.**
   - In `sweep` propone anche cancellazioni: righe di CLAUDE.md che nessuna sessione ha mai violato o che il modello rispetta già da solo, verificate con "would removing this cause a mistake?".
   - Ordine di preferenza per ogni lezione: lint o test, poi hook (`kit.json`), poi skill di progetto, e solo per ultimo una riga in CLAUDE.md.
   - Budget del testo sempre caricato: circa 5k token, misurato con `/context`.
6. **Il rito a ogni nuovo modello** (R1), una sezione nel README:
   - lanciare `/doctor prompt-audit` sul kit e sui CLAUDE.md;
   - rilanciare gli eval del kit con e senza il kit;
   - cancellare ciò che non dà più differenza.
7. **Un loop di pulizia al posto di `/kit:techdebt`.** Una riga in `lead.loops` o una routine: ogni giorno `/simplify` più `/code-review` sui merge del giorno, con una PR piccola se c'è qualcosa. È il "garbage collection" del team OpenAI e il "post-merge sweeper" di Boris.
8. **Il babysit con gli strumenti nativi.** `/kit:go` usa `/autofix-pr` se c'è la Claude GitHub App, altrimenti `/loop 5m /kit:go babysit`.

### 4.3 Misurare prima di tagliare

I tuoi eval sono già lo strumento giusto: `claude plugin eval` confronta con e senza plugin.

- **Fase 0, una sera, circa 40-60 USD.** Lancia i 9 casi mai eseguiti, ciascuno in tre bracci:
  - nessun kit;
  - kit 0.10;
  - `kit-lite`, il branch con i tagli della §4.1.

  Guarda soprattutto *quali casi cambiano esito*, non solo il punteggio medio (Anthropic, ott 2026), e ripeti ogni caso almeno 3 volte.
- **Regola di decisione:** un componente resta se un caso lo separa (Δ > 0 nel braccio con il componente) o se è un invariante deterministico (gate, protect, guard). Altrimenti va via.
- **Casi nuovi utili:**
  - un bug che si trova solo eseguendo il codice (il README §4 lo chiede già);
  - captain con 3 messaggi: risposte di 4 righe o meno, worker lanciati, silenzio sul no-op;
  - una run notturna di 3 iterazioni con un'iterazione che si ferma a metà (per R12).

---

## 5. Prima e dopo

| | Oggi (0.10) | Proposta (1.0 core) |
|---|---|---|
| Skill nel core | 17 | 7: `captain`, `shape`, `go`, `investigate`, `overnight`, `learn`, `init` (più `intake` solo su richiesta) |
| Agenti | 4 | 2: `implementer`, `reviewer` (l'ex verifier, usato al PR) |
| Script hook (più `kitlib.py`) | 8 | 5: `session_start` (solo i gate), `protect`, `guard`, `on_edit`, `stop_check` |
| Punti che iniettano testo | 5, di cui 2 ripetuti (richiamo contesto ogni 5 tool call, modalità loop a ogni prompt) | 1 (`session_start`, una volta) |
| Workflow | 2 | 0 (nativi) |
| Skill vendored | 2 | 0 |
| Plugin di dominio | dentro il core | `kit-llm`, `kit-ui` (scope progetto) |
| Testo sempre caricato del kit | ~1,7k token più promemoria | ~0,5k token |
| Istruzioni totali (corpo skill + agenti) | ~29k token | ~9k token (stima) |

---

## 6. Piano a fasi

**Fase 0: misura** (prima di tutto)
- `/doctor prompt-audit` su `plugins/kit`.
- Eval su tre bracci (§4.3).
- Prova di una settimana di Claude Projects su un repo, registrata in `CATALOG.md` come `trial`.

*Fatto quando:* tabella dei Δ per caso nel README §4 e decisione su Projects.

**Fase 1: tagli a basso rischio** (0.11)
- Tutto il §4.1.
- Il test di budget del §4.2.1.
- README da circa 750 a circa 150 righe, più `docs/`.

*Fatto quando:* test esistenti verdi, test di budget verde, `claude plugin validate` pulito, eval di `kit-lite` almeno pari a 0.10.

**Fase 2: il loop** (0.12)
- `kit:captain` da circa 40 righe.
- Template delle istruzioni per Projects in `docs/`.
- Verifier che diventa reviewer al confine del PR.
- Effort per ruolo.
- Pannello senza testo in modalità loop.

*Fatto quando:* l'eval `lead-captain-dispatches` passa e una sessione reale di una giornata finisce con PR giudicabili senza leggere il diff.

**Fase 3: il cricchetto** (1.0)
- §4.2 punti 3-8: skill e2e da `init`, `overnight` per Opus 5.5, `learn` che pota, rito per i nuovi modelli, loop di pulizia, babysit nativo.

*Fatto quando:* una run notturna reale chiude senza fermate a metà, e `learn sweep` propone almeno una cancellazione.

---

## 7. Cosa non cambierei

- **`kit.json`**, cioè i gate di progetto in un file versionato. È la parte più vicina a quello che le prove dicono funzionare.
- **L'idea della PR giudicabile senza leggere il diff** (intento, evidenza dal vivo, rischio): è il "umano ai due estremi" di R8.
- **La disciplina di `CATALOG.md` e `/kit:intake`**: la popolarità non è una prova, e le tue righe su taste-skill e programbench lo dimostrano.
- **Il runner notturno a contesto fresco con commit sul gate.** Converge con Ralph, gnhf e la guida "long-running" di Anthropic.
- **`guard` e la sandbox per i run autonomi.** Willison: la modalità YOLO va usata solo dentro una sandbox.

---

## Fonti

**Anthropic, docs e guide (lette direttamente)**
- Prompting Claude Opus 5.5: https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-opus-5-5
- Prompting Claude Opus 5 (verifica, delega, autocorrezione): https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-opus-5
- Prompting best practices: https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices
- Skill authoring best practices: https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices
- Claude Code: skills (budget del listing all'1%, 1.536 caratteri, 5k token dopo la compattazione), best practices, memory (meno di 200 righe), sub-agents (`--agent` sostituisce il system prompt), Claude Projects, agent view, goal, scheduled tasks, workflows, plugin evals: https://code.claude.com/docs/en/
- Changelog di Claude Code (versioni delle funzioni native): https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md
- Harness design for long-running apps (24 mar 2026): https://www.anthropic.com/engineering/harness-design-long-running-apps
- Effective context engineering (29 set 2025): https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- Multi-agent research system (giu 2025): https://www.anthropic.com/engineering/built-multi-agent-research-system
- When to fold subagents into your main agent loop (22 ott 2026): https://claude.com/resources/articles/building-agents-when-to-fold-subagents-into-your-main-agent-loop
- Getting started with loops (30 giu 2026): https://claude.com/resources/articles/getting-started-with-loops
- Verification loops with skills (22 lug 2026): https://claude.com/resources/articles/building-verification-loops-in-claude-code-with-skills
- Steering Claude Code (18 giu 2026): https://claude.com/resources/articles/steering-claude-code-skills-hooks-rules-subagents-and-more
- The making of Claude Code: https://www.anthropic.com/engineering/making-of-claude-code

**Team Claude Code** *[sec. dove indicato]*
- Boris Cherny, `/go` e verifica "2-3x" (16 apr 2026): https://x.com/bcherny/status/2044847858634064115
- Boris Cherny, "My job is to write loops" (Acquired, 2 giu 2026) *[sec.]*: https://github.com/cocodedk/loop-engineering
- Thariq Shihipar, "The new rules of context engineering for Claude 5 generation models" (24 lug 2026) *[sec.]*: https://x.com/trq212/status/2080710971228918066

**Prove misurate**
- Gloaguen et al., Evaluating AGENTS.md (ICLR 2026): https://arxiv.org/abs/2602.11988
- Khatri, two-agent ablation of context files (lug 2026) *[sec.]*: https://arxiv.org/abs/2607.27250
- programbench-bench (linee guida e TDD imposti): https://github.com/kunchenguid/programbench-bench
- IFScale: https://arxiv.org/abs/2507.11538. Replica Arize 2026: https://arize.com/blog/llm-instruction-following-benchmark-2026/
- SWE-Skills-Bench (39 skill su 49 senza effetto) *[sec.]*: https://arxiv.org/abs/2603.15401
- Vercel, AGENTS.md vs skills *[sec.]*: https://vercel.com/blog/agents-md-outperforms-skills-in-our-agent-evals
- Vercel, "We removed 80% of our agent's tools" *[sec.]*: https://vercel.com/blog/we-removed-80-percent-of-our-agents-tools
- mini-swe-agent (circa 100 righe, solo bash): https://github.com/SWE-agent/mini-swe-agent

**Praticanti**
- Geoffrey Huntley, Ralph: https://ghuntley.com/ralph/. Playbook: https://github.com/ghuntley/how-to-ralph-wiggum
- HumanLayer, Advanced Context Engineering: https://github.com/humanlayer/advanced-context-engineering-for-coding-agents
- Kun Chen: firstmate https://github.com/kunchenguid/firstmate; gnhf https://github.com/kunchenguid/gnhf; "Your AGENTS.md is a Neural Net" https://blog.kunchenguid.com/p/your-agentsmd-is-a-neural-net
- obra/superpowers: https://github.com/obra/superpowers
- Simon Willison, Designing agentic loops: https://simonwillison.net/2025/Sep/30/designing-agentic-loops/. Su Gas Town (ago 2026): https://simonwillison.net/2026/Aug/4/steve-yegge/
- Mitchell Hashimoto, My AI Adoption Journey (feb 2026) *[sec.]*: https://mitchellh.com/writing/my-ai-adoption-journey
- OpenAI, Harness engineering (11 feb 2026) *[sec.]*
- Cognition, Multi-Agents: What's Actually Working (22 apr 2026) *[sec.]*

---

## Come è stata implementata

Differenze rispetto alla proposta, decise con l'utente il 23 ottobre 2026:

- **Claude Projects non è ancora disponibile**, né da terminale né su questo account. Quindi
  `kit:lead` non è il "captain snello" della §3: è **Claude Projects ricostruito per il
  terminale**. Ha una conversazione che smista ogni messaggio, un thread in background per ogni
  pezzo di lavoro (`kit:implementer` nel proprio worktree, che arriva fino alla PR e alla CI
  verde), una board con gli stati di Projects (`working`, `review`, `needs-you`, `landing`,
  `done`), regole permanenti dette dall'utente salvate nella board, e una notifica quando un thread
  finisce mentre l'utente è via. Il loop mode del pannello manda ogni messaggio al coordinatore con
  una sola riga di contesto. Quando Projects arriverà in CLI, si confronta con `kit:lead` e se ne
  tiene uno (riga in `CATALOG.md`).
- **I plugin di dominio si offrono da soli.** La nuova skill `kit:extras` (circa 400 caratteri sempre
  caricati) riconosce un lavoro UI o LLM in un progetto senza `kit-ui` o `kit-llm` e chiede "Vuoi
  usare Kit UI/LLM per questo?". Su "sì, per questo progetto" installa il plugin con scope progetto e
  lo usa subito leggendo la skill dal marketplace, senza `/reload-plugins`.
- **Nomi tenuti per continuità:** `kit:lead` (come prima, `/loop 30m /kit:lead next` continua a
  funzionare) e `kit:verifier` (la memoria di progetto dei pitfall è legata al nome). Il verifier
  cambia ruolo: è una review a contesto pulito al confine del PR, usata per rischio medio o alto.
- **`kit-llm`** ha due skill invece di quattro: `llm-evals` contiene `prompt-optimize.md` e
  `model-select.md` come file collegati. Il suo hook è ora attivo dovunque il plugin è
  installato.
- **Non fatto:** l'eval a tre bracci "prima di tagliare". I tagli sono stati fatti subito su richiesta
  dell'utente; gli eval si eseguono ora sul kit 1.0 contro nessun kit.

Misure dopo l'implementazione (`claude plugin details`, stesso metodo per entrambe le versioni):
il testo sempre caricato del plugin core passa da **circa 2.718 a circa 1.340 token**. Lo strumento
conta anche le descrizioni delle skill solo-utente, che secondo la documentazione non entrano nel
contesto: il costo effettivo è circa 870 token. In più spariscono le iniezioni periodiche (il
richiamo del contesto ogni 5 tool call e il testo di circa 80 parole del loop mode a ogni prompt).
Il nuovo test `tests/test_budget.py` impedisce di tornare indietro senza accorgersene.
