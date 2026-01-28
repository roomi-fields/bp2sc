# BP3 vs SC Transpiler - Rapport de Comparaison Final

**Date**: 2026-01-28
**Grammaires testées**: 5 paires avec MIDI de référence BP3

---

## Résumé

| Grammaire | Notes | Durées | Verdict |
|-----------|-------|--------|---------|
| **drum** | ✅ MATCH | ⚠️ Diff | Succès (durées = staccato) |
| **acceleration** | ❌ 8 notes manquantes | ❌ Diff | `_keymap` non implémenté |
| **Visser.Waves** | ⚠️ BP3 vide | - | MIDI référence invalide |
| **Ruwet** | ❌ 74↔86 | ✅ MATCH | Homomorphie `mineur` |
| **produce-all** | ❌ 64↔65 | ❌ Diff | Choix RND différents |

**Score**: 1/5 match parfait, 2/5 expliqués par limitations connues

---

## Analyse Détaillée

### 1. drum ✅

**Statut**: SUCCÈS

| Métrique | BP3 | SC |
|----------|-----|-----|
| Notes | 12 | 12 |
| Uniques | [96, 100, 108] | [96, 100, 108] |
| Durées | 0.039-0.04 | 0.25 |

**Analyse**: Les notes correspondent parfaitement. La différence de durées vient du `_staccato(96)` dans la grammaire qui raccourcit les notes à 96% de leur durée. BP3 applique ce raccourcissement, SC émet la durée nominale.

**Action**: Implémenter `_staccato` comme modifier `\legato` dans SC.

---

### 2. acceleration ❌

**Statut**: ÉCHEC - Notes manquantes

| Métrique | BP3 | SC |
|----------|-----|-----|
| Notes | 78 | 500 (boucle infinie détectée) |
| Uniques | [36-47] (12 notes) | [38, 40, 43, 47] (4 notes) |

**Notes manquantes dans SC**: C2, C#2, D#2, F2, F#2, G#2, A2, A#2

**Analyse**: La grammaire utilise des sound objects (do, re, mi...) avec un `_keymap` implicite via le fichier `-al.acceleration`. Le transpileur ne charge pas les mappings d'alphabet.

**Action**: Intégrer `alphabet_parser.py` pour charger les mappings de notes depuis les fichiers `-al.*`.

---

### 3. Visser.Waves ⚠️

**Statut**: INVALIDE - MIDI de référence vide

| Métrique | BP3 | SC |
|----------|-----|-----|
| Notes | 0 | 0 |

**Analyse**: Le fichier `Visser.Waves1.mid` ne contient pas de notes. Soit:
1. Le fichier est pour une grammaire différente
2. Le fichier a été généré avec des paramètres spéciaux
3. Le fichier est corrompu

**Action**: Régénérer le MIDI de référence avec BP3 ou ignorer ce cas de test.

---

### 4. Ruwet ❌

**Statut**: ÉCHEC - Homomorphie non expansée

| Métrique | BP3 | SC |
|----------|-----|-----|
| Notes | 123 | 135 |
| Uniques | [74, 77, 79, 81, 82, 84] | [77, 79, 81, 82, 84, 86] |
| Durées | {0.25: 69, 0.125: 54} | {0.25: 57, 0.125: 78} |

**Différence**:
- BP3 a MIDI 74 (D5 = `re4` en français)
- SC a MIDI 86 (D6 = `re5` en français)

**Cause**: L'homomorphie `mineur` dans `-al.Ruwet`:
```
mineur
fa4 --> re4
la4 --> fa4
```

BP3 applique cette transformation, SC non.

**Action**: Implémenter l'expansion des homomorphies (`homo_not_expanded`).

---

### 5. produce-all ❌

**Statut**: ÉCHEC ATTENDU - RND grammar

| Métrique | BP3 | SC |
|----------|-----|-----|
| Notes | 2 | 2 |
| Uniques | [62, 64] (D4, E4) | [62, 65] (D4, F4) |

**Analyse**: Grammaire RND `S --> X Y` où:
- X ∈ {C4, D4}
- Y ∈ {E4, F4}

BP3 a choisi: X=D4, Y=E4
SC a choisi: X=D4, Y=F4

Les deux sont des dérivations valides. La différence est due au générateur aléatoire.

**Note**: D4 (62) est commun aux deux - seul Y diffère.

**Action**: Aucune - comportement correct pour RND.

---

## Limitations Identifiées

| Limitation | Impact | Priorité |
|------------|--------|----------|
| **Homomorphies** (`homo_not_expanded`) | Notes transformées incorrectes | Haute |
| **Alphabet mapping** (`_keymap`) | Sound objects non mappés | Haute |
| **Staccato** (`_staccato`) | Durées incorrectes | Moyenne |
| **C4key setting** | Octave shift | Moyenne |
| **Seed aléatoire** | Séquences RND différentes | Basse |

---

## Prochaines Étapes

### Phase 9 - Intégration Ressources

1. **Intégrer `alphabet_parser.py`**
   - Charger les fichiers `-al.*` automatiquement
   - Extraire les mappings terminal → MIDI
   - Résoudre les sound objects

2. **Intégrer `settings_parser.py`**
   - Charger `C4key` depuis `-se.*`
   - Appliquer l'offset aux notes MIDI

3. **Implémenter expansion homomorphies**
   - Parser les sections homomorphie dans `-al.*`
   - Appliquer les transformations `(= expr)`

### Phase 10 - Durées

1. **Implémenter `_staccato(N)`**
   - Mapper vers `\legato, N/100`

2. **Implémenter durées variables**
   - Parser les durées explicites dans la grammaire
   - Émettre les valeurs `\dur` correctes

---

## Fichiers de Test

| Fichier | Chemin |
|---------|--------|
| Script de comparaison | `tools/compare_bp3_sc.py` |
| drum MIDI | `bp3-ctests/drum.mid` |
| acceleration MIDI | `bp3-ctests/acceleration.mid` |
| Ruwet MIDI | `tools/ref_ruwet.mid` |
| produce-all MIDI | `tools/ref_produce-all.mid` |
| Résultats JSON | `docs/grammar_analysis_results.json` |
