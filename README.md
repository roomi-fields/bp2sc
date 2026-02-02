# bp2sc -- Transpileur Formel BP3 vers SuperCollider Patterns

**bp2sc** est un transpileur Python qui convertit les fichiers de grammaire
[Bol Processor BP3](https://bolprocessor.org/) en code SuperCollider Pattern
(fichiers `.scd`), base sur un formalisme en trois niveaux.

```
.bp  -->  Grammaire EBNF  -->  AST Formel  -->  Regles de Traduction  -->  .scd
```

---

## Architecture Formelle

Le transpileur repose sur trois niveaux de specification :

```
 1. Grammaire EBNF XML          docs/bp3_ebnf.xml
    (specification normee)       ~60 productions couvrant toute la syntaxe BP3
         |
         v
 2. AST Formel                  docs/bp3_ast_spec.md + src/bp2sc/ast_nodes.py
    (representation typee)       20+ dataclasses Python avec invariants
         |
         v
 3. Regles de Traduction        docs/bp3_to_sc_rules.md
    (compilation dirigee)        Chaque noeud AST -> code SC deterministe
```

### Pipeline

```
Fichier .bp
    |
    v
parser.py          Pre-processeur ligne par ligne + parser regex
                   Classifie: commentaires, headers, modes, preambles, regles
                   Parse chaque regle: poids, flags, LHS --> RHS
    |
    v
ast_nodes.py       Arbre de syntaxe formel: BPFile > GrammarBlock > Rule
                   Elements: Note, Rest, NonTerminal, Variable, Wildcard,
                   Polymetric, SpecialFn, Lambda, HomoApply, TimeSig, Annotation
    |
    v
sc_emitter.py      Compilation dirigee par la syntaxe (syntax-directed)
                   Respecte 6 invariants:
                     INV-1: Pas de commentaires dans les arrays SC
                     INV-2: Pas d'entiers MIDI nus dans Pseq
                     INV-3: Delimiteurs equilibres
                     INV-4: Pdefs terminaux utilisent Pseq([midi], 1)
                     INV-5: Event.silent() pour rests en contexte pattern
                     INV-6: Event.silent(0) pour corps Pdef vide
    |
    v
Fichier .scd       Code SuperCollider idiomatique, pret pour le morphing live
```

---

## Installation

Prerequis : **Python 3.11+**

```bash
# Installation en mode developpement
pip install -e .

# Avec les dependances de dev (pytest)
pip install -e ".[dev]"
```

La seule dependance runtime est [`lark`](https://github.com/lark-parser/lark).

---

## Recuperer les exemples BP3

```bash
git clone https://github.com/bolprocessor/bp3-ctests.git
```

---

## Utilisation CLI

```bash
# Transpiler un fichier BP3 vers .scd
python -m bp2sc input.bp -o output.scd

# Exemple avec le Kathak tihai
python -m bp2sc bp3-ctests/-gr.12345678 -o output.scd

# Exemple avec Ruwet (theme-and-variation)
python -m bp2sc bp3-ctests/-gr.Ruwet -o output_ruwet.scd

# Lister les regles parsees (debug)
python -m bp2sc --list-rules bp3-ctests/-gr.Ruwet
```

### Options

| Option             | Description                                       |
|--------------------|---------------------------------------------------|
| `-o`, `--output`   | Chemin du fichier `.scd` de sortie (defaut: stdout)|
| `--start-symbol`   | Symbole de depart de la grammaire (defaut: `S`)   |
| `--seed N`         | Graine aleatoire pour Prand deterministe (Pseed)  |
| `--alphabet-dir`   | Repertoire contenant les fichiers `-al.*`         |
| `--max-dur N`      | Duree max en beats (Pfindur anti-timeout)         |
| `--list-rules`     | Afficher les regles parsees et quitter             |
| `--verbose`        | Sortie detaillee                                   |

---

## Lancer dans SuperCollider

1. Ouvrir le fichier `.scd` genere dans l'IDE SuperCollider.
2. Demarrer le serveur audio :
   ```supercollider
   s.boot;
   ```
3. Selectionner tout le code et executer : **Ctrl+Enter**.
4. Pour arreter : **Ctrl+.** (ou **Cmd+.** sur macOS).

---

## Morphing live

Le code genere utilise `Pdef` / `Pbindef`, ce qui permet de modifier les
patterns en temps reel sans interrompre la lecture.

```supercollider
// Remplacer un motif
Pdef(\motifA, Pbind(\midinote, Pseq([60, 64, 67], inf), \dur, 0.25));

// Transposer
Pbindef(\main, \ctranspose, 7);

// Changer la densite rythmique
Pbindef(\main, \dur, 0.125);

// Changer d'instrument
Pbindef(\main, \instrument, \synthB);
```

---

## Specification Formelle

| Document | Contenu |
|----------|---------|
| [`docs/bp3_ebnf.xml`](docs/bp3_ebnf.xml) | Grammaire EBNF XML (ISO 14977) -- specification normee de la syntaxe BP3 |
| [`docs/bp3_ast_spec.md`](docs/bp3_ast_spec.md) | Specification de l'AST -- types, invariants, exemples BP3 -> AST |
| [`docs/bp3_to_sc_rules.md`](docs/bp3_to_sc_rules.md) | Regles de traduction -- chaque noeud AST -> code SC |
| [`docs/formalism_reference.md`](docs/formalism_reference.md) | Reference du formalisme -- choix de design, sources |
| [`docs/sc_idioms.md`](docs/sc_idioms.md) | Guide pratique SuperCollider Patterns |

---

## Constructs BP3 Supportes

| Construct                       | Support     | Notes                                       |
|---------------------------------|-------------|---------------------------------------------|
| Modes de grammaire              | Complet     | ORD, RND, LIN, SUB1                         |
| Regles `gram#N[M]`             | Complet     | LHS `-->` RHS                               |
| Poids `<50>`, `<50-12>`        | Complet     | Poids et decrement (Prout mutable)          |
| Flags `/Ideas=20/`, `/NumR+1/` | Complet     | Condition, increment, decrement, comparaison |
| Notes solfege francais          | Complet     | `do4`, `re5`, `sib4`, `fa#3`                |
| Notes sargam indien             | Complet     | `sa6`, `re6`, `ga6`, `pa7`                  |
| Notes anglo (avec alterations)  | Complet     | `C#4`, `Bb3`                                |
| Silences                        | Complet     | `-` (determine), `_` (indetermine)          |
| Non-terminaux                   | Complet     | `S`, `Tihai`, `P4`                          |
| Variables                       | Complet     | `\|x\|`, `\|y\|`                            |
| Wildcards                       | Partiel     | `?1`, `?2` (emis comme Rest + warning)      |
| Expressions polymetriques       | Complet     | `{3, A B C}`, `{A B, C D}`, `{1/2, X Y}`    |
| `lambda`                        | Complet     | Production vide                              |
| Homomorphismes `(= ...)` `(: ...)` | Partiel  | Transformation MIDI inline des elements     |
| Signatures temporelles          | Complet     | `4+4+4+4/4` parse, emis en commentaire      |
| Annotations `[texte]`           | Complet     | Emises en commentaire avant le Pdef          |

### Fonctions speciales supportees

| Fonction | Mapping SC | Exemple |
|----------|-----------|---------|
| `_transpose(N)` | `\ctranspose, N` | `_transpose(-2)` → transposition -2 demi-tons |
| `_vel(N)` | `\amp, N/127` | `_vel(100)` → amplitude 0.787 |
| `_volume(N)` | `\amp, N/127` | `_volume(80)` → amplitude 0.63 |
| `_rndvel(N)` | `\amp, Pwhite(lo, hi)` | `_rndvel(20)` → variation aleatoire ±20 |
| `_mm(BPM)` | `TempoClock.tempo = BPM/60` | `_mm(120)` → 120 BPM |
| `_ins(name)` | `\instrument, \name` | `_ins(Vina)` → SynthDef `\vina` |
| `_pitchbend(N)` | `\detune, N` | `_pitchbend(100)` → detune cents |
| `_staccato(N)` | `\legato, N/100` | `_staccato(50)` → legato 0.5 |
| `_legato(N)` | `\legato, N/100` | `_legato(120)` → legato 1.2 |
| `_chan(N)` | `\chan, N` | `_chan(2)` → canal MIDI 2 |
| `_tempo(N)` | `\stretch, 1/N` | `_tempo(2)` → double vitesse |
| `_press(N)` | `\aftertouch, N/127` | `_press(127)` → aftertouch max |
| `_scale(name, root)` | `\scale/\tuning, \root` | `_scale(Cmaj, 0)` → Scale.major |
| `_script(MIDI program N)` | `\program, N` | `_script(MIDI program 43)` → program 43 |
| `_repeat(N)` | `Pn(pattern, N)` | `_repeat(4) X` → repete X 4 fois |
| `_retro` | `reversed(elements)` | `{_retro A B C}` → C B A |
| `_rotate(N)` | `rotate(elements, N)` | `{_rotate(1) A B C}` → B C A |
| `_rndtime(N)` | `\dur, Pwhite(lo, hi)` | `_rndtime(10)` → variation timing ±10% |

---

## Support MusicXML Import

bp2sc supporte **100%** des constructions generees par l'importeur MusicXML
de Bernard (`_musicxml.php`). Ceci permet de transpiler vers SuperCollider
tous les fichiers BP3 issus d'imports MusicXML.

### Constructions MusicXML supportees

| Construct | Syntaxe BP3 | Mapping SC |
|-----------|-------------|------------|
| Notes liees (tie start) | `C4&`, `fa4&` | `\legato, 2.0` (note tenue) |
| Notes liees (tie end) | `&C4`, `&fa4` | `Event.silent(0.25)` |
| Tempo inline | `\|\|120\|\|` | `\stretch, 0.5` (relatif a 60 BPM) |
| Variation timing | `_rndtime(10)` | `\dur, Pwhite(0.225, 0.275)` |
| Pedale sustain | `_sustainstart_`, `_sustainstop_` | `\sustain, 1/0` |
| Pedale sostenuto | `_sostenutostart_`, `_sostenutostop_` | `\sostenuto, 1/0` |
| Pedale soft | `_softstart_`, `_softstop_` | `\softPedal, 1/0` |
| Slur (liaison) | `_legato_`, `_nolegato_` | `\legato, 1.5/0.8` |
| Marqueur de partie | `_part(N)` | Commentaire (pas de warning) |

### Verification de compatibilite

```bash
# Transpiler un fichier MusicXML importe
python -m bp2sc fichier_musicxml.bp -o output.scd --verbose

# Verifier 0 warnings unsupported_fn pour les elements MusicXML
python -m bp2sc fichier_musicxml.bp --check-warnings
```

---

## Tests

```bash
python -m pytest tests/ -v
```

160+ tests couvrant :

- **test_parser.py** -- Parsing de tous les constructs BP3
- **test_emitter.py** -- Generation SC avec validation des invariants
- **test_note_converter.py** -- Conversion MIDI pour les 3 conventions
- **test_golden.py** -- Non-regression sur `12345678.bp` et `ruwet.bp`
- **test_corpus.py** -- Parsing des 55 grammaires du corpus bp3-ctests

---

## Fonctionnalites Non Supportees

### Fonctions speciales non implementees

| Fonction | Raison | Comportement actuel |
|----------|--------|---------------------|
| `_goto(gram, rule)` | Necessite moteur de derivation | Commentaire TODO + warning |
| `_failed(gram, rule)` | Necessite moteur de derivation | Commentaire TODO + warning |
| `_script(...)` (sauf MIDI program) | Commandes externes variees | Commentaire TODO + warning |
| `_cont(slide)`, `_fixed(slide)` | Controle continu complexe | Commentaire + warning |
| `_pitchcont`, `_pitchfixed` | Pitch bend continu | Commentaire + warning |
| `_volumecont`, `_modcont`, `_presscont` | Controleurs continus MIDI | Commentaire + warning |

### Constructs syntaxiques non supportes

| Construct | Raison | Comportement actuel |
|-----------|--------|---------------------|
| Wildcards `?1`, `?2`, ... | Pattern matching BP3 | Emis comme `Rest()` + warning |
| Regles context-sensitive | Necessite moteur de derivation | Contexte ignore + warning |
| `_switchon(N, M)`, `_switchoff(N, M)` | Switches MIDI | Commentaire + warning |
| Fichiers `-ho.*` (homomorphismes) | Format non documente | Non charges |
| Fichiers `-cs.*` (csound) | Hors scope | Non charges |
| Sound objects `<<name>>` | Format non documente | Non supportes |

### Limitations structurelles

| Limitation | Impact | Contournement |
|------------|--------|---------------|
| Flags non simules | `/Ideas=20/` parse mais pas execute | Expansion manuelle |
| Homomorphismes partiels | `(= X)` et `(: X)` emettent les elements mais pas la transformation complete | Utiliser `--alphabet-dir` pour mapping basique |
| Signatures temporelles | `4+4+4+4/4` parse, emis en commentaire | Definir manuellement dans SC |
| Fichiers `-se.*` | Settings non charges automatiquement | Specifier `--seed`, tempo dans preamble |

### Statistiques actuelles

| Metrique | Valeur |
|----------|--------|
| Grammaires parsees | 55/55 (100%) |
| Tests | 138 passes |
| Warnings totaux (corpus) | 234 |
| Comparaison MIDI | 3/8 matches (37.5%) |

Voir [`docs/formalism_reference.md`](docs/formalism_reference.md) pour la table
complete des constructs exclus et les pistes d'implementation futures.

---

## Licence

Projet en cours de developpement.
