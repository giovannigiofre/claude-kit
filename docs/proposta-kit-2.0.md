# Kit 2.0: la prova prima della PR, e meno attrito

Proposta del 29 ottobre 2026, scritta dopo una ricerca su cinque fronti, sei giorni dopo
[kit 1.0](proposta-kit-1.0.md):

- cosa è cambiato in Claude Code (2.1.250 → 2.1.312) e cosa è diventato nativo;
- le guide Anthropic di agosto-ottobre, Fable 5.1 compreso;
- gli harness e i loop dei practitioner (superpowers, gstack, no-mistakes, backpass, i plugin
  ufficiali, hookify) e le idee nuove dentro;
- le prove misurate del 2026 su cosa aiuta e cosa degrada un agente di codice;
- lo stack dei progetti (Next.js + Supabase su Vercel e Cloudflare, Python su GCP, feature LLM).

I rapporti completi sono stati scritti nel corso della sessione; le fonti sono in fondo. Quelle
segnate *[sec.]* sono state lette tramite riassunti o estratti, perché il sito non era
raggiungibile dalla sessione (arxiv.org, x.com, simonwillison.net, vercel.com, metr.org).

> **Stato: implementata in kit 1.4** (29 ottobre 2026) per la parte deterministica che
> l'utente ha tenuto. Lo stesso giorno l'utente ha deciso che il guard resta quello di 1.3:
> le regole su deploy, segreti in git, push altrove e fail-closed, e il blocco della PR senza
> gate registrato, sono state costruite e tolte (restano descritte qui e in CATALOG.md). Le
> opzioni che cambiano il modo di lavorare restano proposte, con la decisione da prendere.

---

## In breve

1. **La regola di kit 1.0 regge, e le prove nuove la rafforzano.** Due studi con numeri
   (Khatri: file di contesto senza effetto misurabile, p=1.00 e 0.66; Liu & Han: cinque modelli
   per tre harness, pass entro 5 punti ma costo fino a 3 volte per l'overhead fisso di ogni passo)
   dicono che il testo sempre caricato si paga a ogni passo e quasi mai si ripaga. Il rumore tra
   due run uguali è 2-6 punti: un eval a una run per braccio non distingue niente.
2. **Il buco più grande non era nelle istruzioni, ma nelle prove.** "I test passano" era una
   frase; niente registrava su quale albero il gate fosse passato. Le PR degli agenti, misurate su
   4.882 PR, lasciano il 27 % delle righe Python cambiate senza nessun test che le esegua. Ora il
   gate registra l'albero su cui è passato (`gate.py`), e la PR lo cita come prova; il blocco
   della PR senza record è stato provato e tolto per scelta dell'utente.
3. **In auto mode Claude modifica i file con `sed` e heredoc**, e un hook su `Write|Edit` non lo
   vede. `protect` e `onEdit` valevano solo per lo strumento Edit. Ora valgono anche per la shell.
4. **Molto è diventato nativo** in sei giorni di changelog: `onFailure: "block"` sugli hook, il
   loop `/loop` che cura la PR da solo, la skill di progetto `verify` eseguita prima di ogni
   commit, `/fewer-permission-prompts`, `/auto-mode-setup`, il tetto nativo di 8 blocchi dello
   Stop hook, `$.ui.notify` nei mod. Il kit usa quello che c'è e toglie quello che duplica.
5. **Fable 5.1 cambia tre cose**: effort di default `high`, tendenza a fare più del chiesto
   (fix vicini, test in più) che una riga misurata da Anthropic riduce senza perdita, e il costo:
   in `-p` fattura crediti senza chiedere. I thread restano su Opus 5.5 (il port di HAProxy di
   Boris Cherny: Opus 5.5 in 9,5 ore contro 12, al 51 % in meno).
6. **Per lo stack ci sono gate precisi, non skill da caricare.** Next.js 16.3 scrive da solo il
   suo blocco in AGENTS.md (Vercel ha ritirato le proprie skill: 100 % con la documentazione
   inclusa nel pacchetto contro il 79 % con le skill); Supabase ha `test db` (pgTAP), `db lint`,
   `stack` per un database per worktree; `squawk` legge una migrazione in un secondo. Sono righe
   di `kit.json`, proposte da `/kit:init` per stack, non un plugin.

---

## 1. Cosa dice la ricerca nuova (R13-R20, in aggiunta a R1-R12 di kit 1.0)

**R13. Un gate che ha girato è una pretesa finché qualcosa non registra su cosa ha girato.**
gstack rifiuta nella merge queue una PR che non è passata da `/ship`; ECLoop (arXiv 2607.28815)
tiene ferme le azioni finché le condizioni di prova non valgono: +4,8-11,8 punti su SWE-bench
Verified, dichiarati dagli autori *[sec.]*. → `gate.py` registra l'hash dell'albero; `status`
dice se il record copre ancora l'albero. Il blocco della PR è stato scartato dall'utente.

**R14. Le PR degli agenti sono poco testate dove cambiano.** Dipongkor et al. (arXiv 2607.18057):
4.882 PR, 5 agenti; il 61,5 % delle righe Java cambiate e il 27 % di quelle Python eseguite da un
test; il 64,8 % delle PR Python senza nessuna riga cambiata coperta. I test scritti da Claude non
sono più deboli di quelli umani (arXiv 2608.15188). → Non si ordina "scrivi test": si mette la
copertura del diff nel gate (`diff-cover --fail-under 80`).

**R15. Il codice degrada e la degradazione si compone.** EMNLP 2026 (arXiv 2606.21804): costruire
sopra codice scritto da agenti abbassa il resolve rate fino a 13,1 punti; i segnali sono le
modifiche a validazione ed error handling e la crescita del codice a valle. GitClear 2026:
blocchi duplicati +81 % (correlazionale). SonarSource (arXiv 2605.20049): codice pulito non cambia
il pass rate ma costa il 7-8 % di token in meno e il 34 % di riletture in meno. → Duplicazione e
dimensione nel `verify`; il loop giornaliero di `/simplify` (proposta 4.2.7 di kit 1.0) resta.

**R16. Una review in più non sempre aiuta.** CR-Bench: un loop Reflexion alza il recall da 27 a
33 % ma dimezza il rapporto segnale/rumore. "Contextual bias" (arXiv 2603.18740): un diff che
reintroduce una vulnerabilità presentato come "security fix" passa i reviewer, Claude Code e
CodeRabbit compresi. → Una sola review a contesto pulito; il verifier riceve brief e branch, non
il racconto del thread, e legge le regole dal branch base (come fa `/code-review` con REVIEW.md).

**R17. L'overhead dell'harness si paga a ogni passo.** Liu & Han (arXiv 2609.20804): 16.581 token
fissi per passo in Claude Code contro 829 in mini-SWE-agent; pass rate entro 5 punti. Prompt-induced
waste (arXiv 2608.01347): "confronta più approcci" moltiplica i token di ragionamento per
2,4-7,4 senza guadagno; `xhigh` costa 2,4-4,5 volte `low` per 0-2 soluzioni in più su 25.
→ `test_budget.py` resta il cricchetto; effort `medium` per i thread; niente prose di
"valuta alternative".

**R18. Il modello nuovo fa di più, non di meno.** Guida Fable 5.1: "might fix nearby code, extend
behavior the task didn't mention, or commit more test files than the change warrants"; con una
riga di scope "unrequested additions and committed test code drop substantially with no
measurable change in task success". I prompt che chiedono di scrivere il ragionamento possono
essere rifiutati (`reasoning_extraction`). → Una riga di scope nell'implementer; un test che vieta
le richieste di ragionamento nel kit.

**R19. Le prove vanno nella PR, non in un repo nuovo.** PixelLeak (settembre 2026): oltre 13.000
screenshot interni in più di 900 repository pubblici, creati da agenti a cui si chiedeva un
prima/dopo senza un posto dove caricarlo. `gh 2.99` ha `--attach`. → `--attach` nelle istruzioni
di PR; il guard chiede prima di `gh repo create` e rifiuta un percorso della macchina nel corpo.

**R20. Un hook che non parte non deve lasciar passare.** Claude Code 2.1.295 (`onFailure:
"block"`), gstack 1.91.218 ("blocks skills when its gate can't run"). → Una riga in
`hooks.json`; l'utente preferisce un guard che in caso di crash lascia passare a uno che ferma
ogni comando finché non viene sistemato. Non adottata.

---

## 2. Cosa era già nativo, e cosa il kit ha fatto

| Nativo (versione) | Nel kit prima | Ora |
|---|---|---|
| `/loop` nudo cura la PR del branch (commenti, CI rossa, conflitti); una prompt schedulata non può invocare una skill solo-utente | `/loop 10m /kit:go babysit` (non eseguiva mai la skill) | `/kit:go` passa a `/loop` nudo; i loop del lead sono scritti in parole |
| skill di progetto `verify` eseguita prima di ogni commit (2.1.286), `/verify`, `/run` | skill `e2e` | `/kit:init` scrive `.claude/skills/verify/SKILL.md` |
| `onFailure: "block"` (2.1.295) | fail open | resta fail open (scelta dell'utente) |
| PermissionRequest hook | `/kit:init` proponeva allow rules | `permission.py`: `check` e `verify` del progetto senza prompt; `/fewer-permission-prompts` per il resto |
| `$.agent.list()` con stato `waiting`, `$.ui.notify` (2.1.289, 2.1.295) | la status line contava solo i running; la notifica era prosa del lead | `N waiting` sulla riga; una notifica nativa quando la board guadagna un item `review` o una domanda |
| tetto nativo di 8 blocchi dello Stop hook, `stop_hook_active` | `maxStopRetries` 3 | resta il 3 del kit, più stretto |
| `claude -p` parte in modalità manuale (2.1.302), `--permission-prompts none` (2.1.259) | il runner notturno ereditava le impostazioni | default `auto` + prompt negati; `--fallback-model`, `--max-turns` |
| `--max-budget-usd`, `--max-turns` | i cap del runner | restano (il runner li somma su più iterazioni) |
| `/auto-mode-setup`, `claude auto-mode config` (2.1.304) | `auto_mode_sync.py` con righe per repo | resta: il nativo scrive righe senza scope, il kit le lega all'origin del repo |
| auto memory per repo, `memory: project` degli agenti | il ledger delle lezioni | resta (da misurare: CTIM-Rover trova che le memorie tra task possono distrarre) |
| Claude Projects (17 settembre), thread sulla tua macchina via Remote Control | `kit:lead` | resta; prova quando arriva sull'account |

---

## 3. Le opzioni, per aspetto

Stato: **fatto** (in kit 1.4), **proposta** (da decidere), **no** (scartata, con il perché).

### Fluidità (meno attrito tra te e il loop)

| Opzione | Stato | Cosa fa |
|---|---|---|
| Gate del progetto senza prompt di permesso | fatto | `permission.py` (PermissionRequest) |
| Status line con i thread in attesa di risposta | fatto | `N waiting` dal `$.agent.list()` |
| Notifica nativa quando la board guadagna lavoro per te | fatto | il mod confronta i conteggi a ogni tick; `$.ui.notify` una volta |
| `/loop` nativo al posto di `/kit:go babysit` schedulato | fatto | la prompt schedulata non caricava la skill |
| Thread come sessioni `claude --bg` + agent view | proposta | persistenza tra terminali, worktree, gruppi "Needs input / Ready for review" nativi, notifiche. Sostituirebbe metà della board. Da provare una giornata contro `kit:lead` |
| `.claude/loop.md` scritto da `/kit:init` | fatto (senza merge automatico) | il `/loop` nudo del progetto: CI, review, conflitti, pulizia; a PR verde si ferma e lo dice; prosa, caricata solo dal loop |
| Rendering delle opzioni di `kit:shape` in pagina annotabile (lavish) | no | già in trial candidate; nessuna prova nuova |

### Efficienza (token, prompt, tempo)

| Opzione | Stato | Cosa fa |
|---|---|---|
| `check` diff-aware | fatto | `KIT_CHANGED_FILES` nell'ambiente di `check` e di `gate.py` |
| Fingerprint dello Stop hook sul contenuto | fatto | un file nuovo modificato due volte rifaceva passare il check una volta sola |
| `model: opus` per i thread | fatto | una sessione su Fable non genera thread a 2,5 volte il prezzo; override per thread dal lead |
| Il runner rifiuta Fable senza `--allow-credits` | fatto | in `-p` fattura crediti senza chiedere |
| Eval a 3 run per braccio, `--model` fissato | fatto (docs) | rumore 2-6 punti |
| Effort per thread dal lead (Agent tool `effort`, 2.1.292) | proposta | `high` solo per item ambigui o architetturali; serve un eval |
| `autoCompactWindow: 200000` sui thread | proposta | su modelli da 1M compatta a 200k: intenzionale per il costo, ma da confermare |
| Ledger delle lezioni: misurare con un braccio senza | proposta | CTIM-Rover *[sec.]*: memorie tra task non battono la baseline |
| Togliere la nota "unattended" di `overnight.py` | proposta (flag) | il bundle di Fable 5.1 porta già "Delivering work" *[sec.]*; `--no-unattended-note` per misurare |

### Autonomia (quanto va avanti da solo senza rompere)

| Opzione | Stato | Cosa fa |
|---|---|---|
| Deploy, migrazioni remote, publish, delete cloud: chiedere | no (scelta) | costruita e tolta: il guard di 1.3 basta; la lista dei comandi è in CATALOG.md se servisse |
| `.env` e chiavi mai in git | no (scelta) | idem; `gitleaks protect --staged` nel `check` copre lo stesso caso senza un hook |
| Push verso un remote che non è origin: chiedere | no (scelta) | idem |
| Regole di progetto deterministiche | fatto | `guard.denyCommands` / `askCommands`, vuote finché un progetto non le scrive; `/kit:learn` le propone (idea da hookify) |
| Hook fail-closed | no (scelta) | `onFailure: "block"` resta una riga documentata in CATALOG.md |
| Edit via shell coperti | fatto | `bash_edits.py` + snapshot del guard |
| Runner notturno: `auto` + prompt negati, fallback model, max turns | fatto | |
| Sweep post-merge (`sweep.py`) | proposta | worktree e branch delle PR mergiate, diff squash-safe, stop su file non tracciati; il lead ora fa la riga minima |
| Decision trail (gstack, no-mistakes) | proposta | un TSV append-only delle decisioni; da misurare, è processo imposto |
| Ultrareview sulle PR ad alto rischio | proposta | 3 run gratuite poi 5-25 $; carica l'albero nel cloud |

### Qualità del codice

| Opzione | Stato | Cosa fa |
|---|---|---|
| Gate registrato sull'albero esatto, citato dalla PR | fatto (solo il record) | `gate.py` registra e `status` confronta; il blocco di `gh pr create` è stato tolto per scelta dell'utente |
| Verifier con brief e branch, regole dal branch base | fatto | R16 |
| Riga di scope nell'implementer | fatto | R18, misurata da Anthropic |
| Prove allegate con `gh --attach` | fatto (istruzione) | R19 |
| Gate per stack in `/kit:init` (`stacks.md`) | fatto | copertura del diff, duplicazione, test affetti, segreti, `supabase test db`, `db lint`, `squawk`, tipi generati e committati |
| Nuova superficie "Database / RLS" e strumenti headless in `evidence-by-surface.md` | fatto | riproduci come il ruolo dell'utente, `explain analyze`, `db diff`; playwright-cli, MCP del dev server Next, MCP Supabase read-only |
| Test del kit contro le richieste di ragionamento | fatto | `test_budget.py` |
| Plugin `kit-supabase` (migrazione + test RLS + prove) | proposta | ~300 token sempre caricati nei repo con `supabase/`; offerto da `kit:extras` |
| Mutation testing sul diff per rischio medio/alto | proposta | minuti di CI; prove sottili e di vendor |
| `kit-web` | no | Next.js 16.3 mette il suo blocco in AGENTS.md e la documentazione nel pacchetto |
| Skill `supabase` di Supabase, Vercel plugin, CodeRabbit | no | processo imposto; telemetria accesa; SaaS che legge la PR |

---

## 4. Cosa è stato implementato (kit 1.4)

Deterministico, stdlib, con un test accanto a ogni pezzo:

- `hooks/scripts/gate.py`: esegue `check` o `verify`, stampa l'output, registra in
  `.claude/evidence/<branch>/gate-<nome>.json` comando, esito, durata, hash dell'albero (contenuto
  committato e non, file ignorati esclusi), se il gate ha modificato file; `status` dice se il
  record copre l'albero com'è ora. `test_gate.py`.
- `guard.py`: regola `project` (`denyCommands` / `askCommands`, vuote di default) e lo
  snapshot dei file sporchi prima di ogni comando Bash, per `bash_edits.py`. Le regole su
  deploy, segreti, push altrove e il controllo PR sono state tolte su richiesta dell'utente.
- `bash_edits.py` (PostToolUse Bash): `onEdit` e `protect` sui file che un comando shell ha
  cambiato. `test_bash_edits.py`.
- `permission.py` (PermissionRequest Bash): `check`, `verify` e gli script del kit senza
  prompt. `test_permission.py`.
- `stop_check.py`: fingerprint sul contenuto dell'albero; `KIT_CHANGED_FILES`. `test_stop_check.py`.
- `kitlib.py`: `changed_files`, `changed_env`, `dirty_snapshot`, `default_branch`.
- `subagent_start.py`: una riga in più per ogni thread con il comando esatto del gate.
- `hooks.json`: matcher ancorati, i due hook nuovi (PermissionRequest, PostToolUse Bash).
- `kit.tsx`: `N waiting`, notifica nativa su variazione della board; test del mod.
- `overnight.py`: `auto` + `--permission-prompts none` di default, `--fallback-model`,
  `--max-turns`, `--allow-credits`, `--no-unattended-note`, comando mostrato in `--dry-run`.
- `tests/test_budget.py`: niente richieste di ragionamento nelle skill, negli agenti e negli hook.

Prosa, cambiata solo dove la ricerca lo giustifica:

- `kit:implementer`: `model: opus`, riga di scope, gate via `gate.py`, `--attach`, skill `verify`.
- `kit:verifier`: gate via `gate.py`; brief e regole dal branch base, non il racconto del thread.
- `kit:lead`: brief del verifier, pulizia del worktree a PR mergiata, loop in parole.
- `/kit:go`: gate via `gate.py` in step 4 e 6, `--attach`, `/loop` nudo per la CI lunga.
- `/kit:init`: skill `verify`, `stacks.md`, compaction con i sei punti della guida 5.1,
  `.worktreeinclude` e `symlinkDirectories`, blocco AGENTS.md di Next.
- `/kit:learn`: `guard.denyCommands` tra le case possibili di una lezione.
- `kit:overnight`: i flag nuovi.
- `kit:investigate` `evidence-by-surface.md`: Supabase, Cloudflare, browser headless, MCP del
  dev server Next, superficie Database / RLS.

Testo sempre caricato: invariato (le descrizioni non cambiano; `test_budget.py` verde). Una riga
in più per thread (circa 60 token) con il comando del gate.

---

## 4b. Kit 1.5: lo stile mailbox di trio-agent-loop (31 ottobre)

L'utente ha portato [albiol2004/trio-agent-loop](https://github.com/albiol2004/trio-agent-loop)
(MIT) e ha chiesto cosa prenderne. Di buono: lo stato vive in file che si leggono con `cat`, si
modificano per sterzare e si riprendono; la prima riga del verdetto è leggibile da una macchina
e uno `scope=local` manda una riparazione mirata invece di ripianificare; le scelte di giudizio
sono righe `DECISION:` che l'utente può vetare; gli scout di `trio-bridge` scrivono schede di
proposta deduplicate per classe. Da non prendere: prompt da centinaia di righe, due Opus a
iterazione, dashboard e driver per dieci harness. Costruiti, approvati prima dall'utente:

- **A. Mailbox per item** (`items.py`, hook SubagentStop anche per `kit:implementer`):
  `.claude/lead/items/<id>/` con BRIEF, REPORT, VERDICT e LOG; gli hook riempiono REPORT e
  VERDICT quando thread e verifier finiscono; il verifier può dire `FAIL scope=local:<file>`;
  l'implementer segna `DECISION:`; il lead rilegge BRIEF prima di ribriffare e archivia a PR
  mergiata.
- **B. Modalità discussione e handoff** (`/kit-mode ask`, `/kit:handoff`): solo istruzione
  (scelta dell'utente), documentazione modificabile, codice no; l'handoff scrive il brief come
  item e lo manda al coordinatore, a una sessione aperta (messaggistica tra sessioni), a una
  sessione nuova in background (`claude --bg`), o lo salva; `card` fa una scheda.
- **C. Schede di proposta** (`/kit:scout`, `proposals.py`): esploratori in sola lettura,
  schede con impronta sha256 e classe A/B/C, `take` che le trasforma in item, ritiro per età.

Costo sempre caricato: zero (le due skill sono solo da tastiera; la riga di contesto di ask
mode arriva solo in quella modalità).

## 4c. Kit 1.6: effort per thread e occhi freschi sul brief (8 novembre)

Verifica chiesta dall'utente: i thread sono "goldfish"? Sì: la documentazione di Claude Code
dice che un subagent parte con un contesto fresco e isolato, senza la conversazione del
coordinatore; un `kit:implementer` vede il suo system prompt, i CLAUDE.md del progetto, uno
snapshot di `git status`, il brief e la riga del kit (lezioni e gate). Il brief è l'unico canale.

Effort: l'implementer aveva `medium` (il default di Opus 5.5); il verifier ereditava il livello
della sessione, quindi da una sessione a `xhigh` partivano review a `xhigh`. La pagina Effort di
Anthropic mette i subagent sotto `low` e chiede uno sweep sugli eval propri invece di ereditare
impostazioni; l'unica misura indipendente (Prompt-Induced Waste, Opus 5) dà `low` 16-17 su 25
contro `high` 18, a un quarto del costo. Fatto: il coordinatore passa l'effort per thread
(`low` per un brief chiaro, piccolo e con i PLACES; `medium` altrimenti; `high` per item
ambigui), gli scout a `low`, il verifier fissato a `medium`; il default resta `medium` finché un
eval a 3 run (`CLAUDE_CODE_EFFORT_LEVEL=low` contro `medium`) non dice altro.

Da Google EGM (Apache-2.0) si è preso un solo meccanismo: una passata a occhi freschi sul brief,
per item grandi o ambigui, che parafrasa, elenca cosa andrebbe indovinato, cosa DONE WHEN non
richiede, cosa esiste da riusare e cosa il brief cita che non esiste. Non presi: la pipeline
spec-driven a cinque stadi, i nove persona, le regole di tono, il "mai un'opzione raccomandata".

## 5. Da decidere (in ordine di impatto)

Decisioni già prese dall'utente il 29 ottobre: guard come in 1.3 (niente regole su deploy,
segreti, push altrove, niente fail-closed), nessun blocco della PR, `loop.md` da `/kit:init`
approvato senza merge automatico; sweep post-merge, `kit-supabase` e ultrareview non ora.

1. **Thread come `claude --bg` + agent view, o `kit:lead` com'è?** Una giornata su un repo con
   entrambi; si tiene chi dà PR giudicabili con meno messaggi.
2. **`kit-supabase`**: vale 300 token sempre caricati nei repo Supabase? Prima si provano le righe
   di `stacks.md` su myinsurance per una settimana; se le ricette RLS vengono richieste tre volte
   a mano, si fa il plugin.
3. **Ultrareview** sulle prime tre PR ad alto rischio, confrontato con `kit:verifier`.
4. **Il ledger delle lezioni** contro un braccio senza, su `verifier-catches-bug` e
   `lead-verifies-before-done`, 3 run ciascuno.
5. **La nota "unattended"**: una notte con `--no-unattended-note` su Opus 5.5 e una senza; si
   conta le fermate a metà.
6. **Mutation testing sul diff**: solo se un eval con un test debole piantato lo separa da
   `diff-cover`.
7. **Il rito del nuovo modello, ora**: `/doctor prompt-audit` e `/skill-doctor` sui plugin; gli
   eval con `--model opus` e `--model fable`, 3 run; cancellare ciò che non sposta il risultato.

---

## Fonti

**Claude Code e Anthropic (lette direttamente)**
- Changelog 2.1.250-2.1.312: https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md
- Hooks, sub-agents, mods, agent view, claude-projects, scheduled-tasks, goal, model-config, best-practices, costs, sandboxing, permission-modes: https://code.claude.com/docs/en/
- Prompting Claude Fable 5.1: https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-fable-5-1
- What's new in Fable 5.1, effort, models overview: https://platform.claude.com/docs/en/models/fable-5-1/whats-new-fable-5-1, https://platform.claude.com/docs/en/build-with-claude/effort
- Lancio Fable e Mythos 5.1 (1 settembre 2026): https://www.anthropic.com/claude-fable-and-mythos-5-1
- Claude Projects, lancio (17 settembre 2026): https://claude.com/blog/projects-redesigned
- Boris Cherny su HAProxy (Opus 5.5 vs Fable 5.1) *[sec.]*: https://x.com/bcherny/status/2102439069053747549

**Prove misurate**
- Khatri, Do Context Files Help Coding Agents? *[sec.]*: https://arxiv.org/abs/2607.27250
- Liu & Han, Empirical Study of Harness Design *[sec.]*: https://arxiv.org/abs/2609.20804
- Vats & Golev, The Scaffold Effect *[sec.]*: https://arxiv.org/abs/2607.22585
- Weinberger & Hozez, Prompt-Induced Waste *[sec.]*: https://arxiv.org/abs/2608.01347
- Dipongkor et al., Test Coverage Analysis of Agentic PRs *[sec.]*: https://arxiv.org/abs/2607.18057
- Is Agent Code Less Maintainable Than Human Code? (EMNLP 2026) *[sec.]*: https://arxiv.org/abs/2606.21804
- Trivedi & Schmitt, Does Code Cleanliness Affect Coding Agents? *[sec.]*: https://arxiv.org/abs/2605.20049
- Xia & Miller, Post-Merge Fate of Agentic Code *[sec.]*: https://arxiv.org/abs/2607.09902
- GitClear, The AI Code Quality Maintainability Gap *[sec.]*: https://www.gitclear.com/the_ai_code_quality_maintainability_gap
- CR-Bench *[sec.]*: https://arxiv.org/abs/2603.11078; Contextual Bias in LLM Security Code Review *[sec.]*: https://arxiv.org/abs/2603.18740
- Static analysers on LLM code *[sec.]*: https://arxiv.org/abs/2602.05868; TDAD *[sec.]*: https://arxiv.org/abs/2603.17973
- ECLoop *[sec.]*: https://arxiv.org/abs/2607.28815; CTIM-Rover *[sec.]*: https://arxiv.org/abs/2608.03392
- HumanLayer, SlopCodeBench Part I (15 ottobre 2026): https://humanlayer.dev/ (post)
- PixelLeak (Glow Labs, 29 settembre 2026) *[sec.]*: https://www.bitdefender.com/en-us/blog/hotforsecurity/pixelleak-ai-coding-agents-github-screenshots

**Practitioner e plugin**
- gh 2.99 `--attach`: https://github.com/cli/cli/releases/tag/v2.99.0
- anthropics/claude-plugins-official (hookify, session-report, receipts): https://github.com/anthropics/claude-plugins-official
- obra/superpowers v7.0.1: https://github.com/obra/superpowers; garrytan/gstack: https://github.com/garrytan/gstack
- kunchenguid no-mistakes v1.104, backpass v0.1.42: https://github.com/kunchenguid
- ArefMozafari/post-merge-cleanup: https://github.com/ArefMozafari/post-merge-cleanup

**Stack**
- supabase/agent-skills, MCP, branching, stack, pgTAP: https://github.com/supabase/agent-skills, https://supabase.com/docs/guides/ai-tools/mcp, https://supabase.com/docs/guides/local-development/running-multiple-local-projects
- Next.js per agenti (16.2+ docs nel pacchetto, 16.3+ blocco AGENTS.md, MCP del dev server): https://github.com/vercel/next.js/blob/canary/docs/01-app/02-guides/ai-agents.mdx
- vercel-labs/agent-skills: https://github.com/vercel-labs/agent-skills; cloudflare/skills e MCP: https://github.com/cloudflare/skills, https://github.com/cloudflare/mcp
- Playwright agents e CLI (1.56-1.64): https://github.com/microsoft/playwright/releases; shadcn MCP: https://ui.shadcn.com/docs/mcp
- squawk: https://github.com/sbdchd/squawk; basejump/supabase-test-helpers: https://github.com/basejump/supabase-test-helpers
- Lighthouse CI, diff-cover, jscpd, knip, gitleaks, Stryker, mutmut, cosmic-ray: i rispettivi repository (licenze in CATALOG.md)
