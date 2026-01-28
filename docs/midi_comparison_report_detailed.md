# Rapport Détaillé : Comparaison MIDI BP3 vs SC Transpiler

**Date** : 2026-01-28
**Grammaires testées** : 55 (corpus bp3-ctests)
**MIDI générés avec BP3** : 7 (13%)
**Comparaisons valides** : 7

## Résumé Exécutif

| Grammaire | Notes BP3 | Notes SC | Résultat | Cause |
|-----------|-----------|----------|----------|-------|
| drum | 12 | 12 | **MATCH** | Grammaire déterministe |
| Ames | 11 | 13 | MISMATCH | Structures polymétrique complexes |
| produce-all | 2 | 2 | MISMATCH | RND - seed différent |
| tryTimePatterns | 8 | 15 | MISMATCH | Notes additionnelles SC |
| checkNegativeContext | 3 | 0 | MISMATCH | Symboles non-note (A, B) sans alphabet |
| vina | 5 | 0 | TIMEOUT | Grammaire complexe (indian notation) |
| Ruwet_test | 1251 | 135 | MISMATCH | Homomorphisme non-expansé |
| Ruwet_ref | 123 | 134 | MISMATCH | D5 ↔ D6 (octave shift) |

**Score final** : 1/7 (14%) correspondance parfaite des notes

---

## Analyses Détaillées

### 1. drum - MATCH

**Grammaire** : `-gr.drum`
**Type** : ORD (ordonnée)

```
S --> C7 E7 {3,C8,C8,C8} {2,C7,C7} E7 C7 E7
```

**Résultat BP3** : 12 notes - [96, 100, 108] (C7, E7, C8)
**Résultat SC** : 12 notes - [96, 100, 108] (C7, E7, C8)

**Analyse** : Grammaire déterministe sans choix aléatoire. Les notes et leurs quantités correspondent parfaitement. Seule différence : la représentation des durées (BP3 en ticks, SC en beats).

---

### 2. Ames - MISMATCH (3 manquantes, 2 extras)

**Grammaire** : `-gr.Ames`
**Type** : ORD avec structures polymétrique

```
S --> {PA, _rest PB}
PA --> {2,- PA1, 2 PA2} {4,PA3}
PA1 --> {2,F#3}
PA2 --> {1,F5,A5}
PA3 --> PA31 PA32
PA31 --> {1/2,G#3,E5,G5}
PA32 --> {7/2,Bb4}
PB --> {1/4,G#5&,C6,E6,B6&} {2,&G#5,&B6}
```

**BP3** : [54, 56, 70, 76, 77, 79, 80, 81, 84, 88] (F#3, G#3, A#4, E5, F5, G5, G#5, A5, C6, E6)
**SC** : [60, 61, 70, 76, 77, 79, 81, 84, 88, 95] (C4, C#4, A#4, E5, F5, G5, A5, C6, E6, B6)

**Cause** :
- Durées `_rest` avec variable non résolue dans SC
- Ties (`&`) entre notes traités différemment
- Notes F#3 et G#3 manquantes en SC (pas de correspondance dans le polymétre)

---

### 3. produce-all - MISMATCH (1 manquante, 1 extra)

**Grammaire** : `produce-all.bpgr`
**Type** : RND (aléatoire)

```
S --> X Y
X --> C4 | D4
Y --> E4 | F4
```

**BP3** (seed 42) : [62, 64] = D4, E4
**SC** (seed interne) : [60, 64] = C4, E4

**Cause** : Grammaire RND. BP3 avec `--seed 42` a choisi D4+E4, le transpiler SC utilise un seed différent ou une implémentation différente de Prand. **Comportement attendu** - les outputs ne doivent pas correspondre exactement.

---

### 4. tryTimePatterns - MISMATCH (0 manquantes, 2 extras)

**Grammaire** : `-gr.tryTimePatterns`
**Type** : ORD avec patterns temporels

**BP3** : [60, 62, 64, 65, 69, 71, 72, 76] (C4, D4, E4, F4, A4, B4, C5, E5)
**SC** : [60, 61, 62, 63, 64, 65, 69, 71, 72, 76] + C#4, D#4

**Cause** :
- Notes C#4 (61) et D#4 (63) générées par SC mais pas par BP3
- Possible différence dans l'interprétation des patterns temporels `{...}` ou des expressions polymétrique

---

### 5. checkNegativeContext - MISMATCH (0 SC notes)

**Grammaire** : `-gr.checkNegativeContext`
**Type** : RND avec contextes négatifs

```
S --> A A2 A3 A1 A A /times=5/
/times > 0/ #A1 #A2 #A3 A A --> #A1 #A2 A A #A3 /times-1/
<0> LEFT #A2 #A1 A --> B B
```

**BP3** : [33, 45, 57] = A1, A3, A5 (octaves d'A)
**SC** : 0 notes

**Cause** :
- Les symboles `A`, `A1`, `A2`, `A3`, `B` sont des non-terminaux, pas des notes MIDI
- BP3 utilise un mapping par défaut `A → MIDI 33` (alphabet interne)
- **Pas de fichier `-al.checkNegativeContext`** pour définir le mapping
- Le transpiler SC n'a pas accès à ce mapping → génère des Pdef vides

---

### 6. vina - TIMEOUT

**Grammaire** : `-gr.vina`
**Type** : Grammaire indienne complexe avec notation sargam

**BP3** : [48, 55, 59, 60] = C3, G3, B3, C4
**SC** : TIMEOUT après 60s

**Cause** :
- Grammaire très complexe avec notation indienne (sa, ri, ga, ma, pa, dha, ni)
- Le transpiler génère du code SC valide mais son exécution dans sclang dépasse le timeout
- Possible boucle infinie ou récursion excessive dans les Pdefs générés

---

### 7. Ruwet_test - MISMATCH (7 manquantes, 6 extras)

**Grammaire** : `-gr.Ruwet`
**Type** : ORD avec homomorphisme

```
GRAM#1
S --> B B B
B --> x x x ... (74 notes)

-HO:
mineur: fa5 --> re5
majeur: fa5 --> mi5
```

**BP3** (1251 notes) : [62, 65, 67, 69, 70, 72, 74] = D4-D5 range
**SC** (135 notes) : [77, 79, 81, 82, 84, 86] = F5-D6 range

**Cause** :
- **Homomorphisme non-expansé** : L'homomorphisme `mineur: fa5 --> re5` applique une transposition. Le transpiler SC génère un warning mais ne peut pas appliquer cette transformation
- **Différence d'octave** : BP3 joue en octave 4-5, SC en octave 5-6
- **Nombre de notes** : BP3 répète beaucoup plus (1251 vs 135) - différence dans l'interprétation de la récursion

---

### 8. Ruwet_ref - MISMATCH (1 manquante, 1 extra)

**MIDI de référence** (ancien fichier) vs **SC transpiler**

**BP3 ref** : [74, 77, 79, 81, 82, 84] = D5, F5, G5, A5, A#5, C6
**SC** : [77, 79, 81, 82, 84, 86] = F5, G5, A5, A#5, C6, D6

**Cause** :
- D5 (74) présent dans BP3 mais pas SC
- D6 (86) présent dans SC mais pas BP3
- **Shift d'octave sur une note** - probablement lié à l'homomorphisme `mineur`

---

## Causes Racines des Divergences

### 1. Grammaires RND (aléatoires)
- **Impact** : produce-all
- **Nature** : Comportement attendu - seeds différents = outputs différents
- **Action** : Aucune - résultat correct mais non-déterministe

### 2. Homomorphismes non-supportés
- **Impact** : Ruwet, Ruwet_test
- **Nature** : Le transpiler ne peut pas appliquer les transformations de notes
- **Action** : Implémenter le support des homomorphismes (Phase future)

### 3. Symboles non-note sans alphabet
- **Impact** : checkNegativeContext
- **Nature** : Les symboles A, B ne sont pas des notes MIDI connues
- **Action** : Charger les fichiers `-al.*` pour le mapping terminal→note

### 4. Structures polymétrique complexes
- **Impact** : Ames, tryTimePatterns
- **Nature** : Les expressions `{n,a,b,c}` avec durées fractionnaires
- **Action** : Améliorer le calcul des durées dans les polymétriques

### 5. Timeouts sur grammaires complexes
- **Impact** : vina
- **Nature** : Récursion excessive dans sclang
- **Action** : Optimiser la génération de code ou limiter la profondeur

---

## Statistiques de Génération MIDI

Sur 55 grammaires BP3 :

| Catégorie | Nombre | % |
|-----------|--------|---|
| MIDI valide (>100 bytes) | 7 | 13% |
| MIDI vide (0 bytes) | 7 | 13% |
| Échec génération | 41 | 74% |

**Causes des échecs** :
- 37 : "vide" - aucune sortie MIDI générée
- 4 : Erreurs de parsing (Csound, dépendances manquantes)

Les grammaires qui échouent utilisent souvent :
- Notation Csound (sound objects)
- Références à des fichiers externes non disponibles
- Grammaires de test syntaxique sans output sonore prévu

---

## Conclusion

Le transpiler BP2SC produit une sortie correcte pour les grammaires simples et déterministes (drum). Les divergences observées sont dues à :

1. **Design intentionnel** : RND grammars = outputs non-déterministes
2. **Fonctionnalités non-implémentées** : Homomorphismes, alphabets custom
3. **Limitations timeout** : Grammaires complexes (vina)

**Prochaines étapes recommandées** :
1. Implémenter le chargement des fichiers `-al.*` pour le mapping des terminaux
2. Supporter les homomorphismes `-ho.*`
3. Optimiser la génération de code pour éviter les timeouts
