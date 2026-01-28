# Analyse des Warnings - Post Phase 8

**Date:** 2026-01-28
**Total:** 243 warnings (réduit de 319, soit -76)

---

## Résumé par Catégorie

| Catégorie | Count | % |
|-----------|-------|---|
| `missing_resource` | 88 | 36% |
| `approximation` | 80 | 33% |
| `unsupported_fn` | 42 | 17% |
| `context_stripped` | 30 | 12% |
| `time_sig_ignored` | 2 | 1% |
| `homo_not_expanded` | 1 | 0% |

---

## Détail : missing_resource (88)

Fichiers de ressources référencés mais non parsés.

| Préfixe | Count | Description | Status |
|---------|-------|-------------|--------|
| `-se.*` | 50 | Settings (tempo, MIDI config, note convention) | **Présents** dans repo |
| `-cs.*` | 16 | CSound orchestra/score | **Absents** |
| `-ho.*` | 9 | Homomorphism definitions | **Absents** (mais données dans `-al.*`!) |
| `-al.*` | 4 | Alphabet/homomorphism mappings | **Présents** |
| `-to.*` | 3 | Tonal scales | Inconnu |
| `-tb.*` | 2 | Tableau | Inconnu |
| `-md.*` | 1 | MIDI device config | Inconnu |
| `-gl.*` | 1 | Glossary | Inconnu |
| `-in.*` | 1 | Interactive | Inconnu |
| `-mi.*` | 1 | MIDI file ref | Inconnu |

### Découverte : Structure des fichiers `-al.*`

Les fichiers `-al.*` contiennent des **définitions d'homomorphismes**, pas des alphabets simples :

```
// -al.Ruwet
m1
la4 --> sib4
------------------
m2
la4 --> sol4
---------------------
mineur
fa4 --> re4
la4 --> fa4
```

Chaque section définit un mapping (nom de l'homomorphisme suivi de règles `note --> note`).

### Opportunité future

Parser les fichiers `-se.*` pour extraire :
- `NoteConvention` : 0=English, 1=French, 2=Indian
- `Pclock/Qclock` : période du métronome → tempo

Parser les fichiers `-al.*` pour :
- Extraire les mappings d'homomorphisme
- Permettre l'expansion des `HomoApply(REF)` avec le bon mapping

---

## Détail : approximation (80)

| Source | Count | Description | Réductible? |
|--------|-------|-------------|-------------|
| `Wildcard` | 55 | `?N` émis comme Rest() | **Non** - nécessite moteur de dérivation |
| `_pitchcont` | 9 | Pitch continu | **Non** - pas d'équivalent SC direct |
| `_pitchrange` | 7 | Plage de pitch | **Non** - paramètre de mapping |
| `_retro` | 4 | Inversion de séquence | **Oui** - pourrait être `.reverse` |
| `_switchon` | 2 | MIDI switch on | **Non** - CC MIDI, SynthDef-dépendant |
| `_switchoff` | 2 | MIDI switch off | **Non** - CC MIDI, SynthDef-dépendant |
| `_scale(unknown)` | 1 | Gamme non reconnue | **Oui** - ajouter au mapping |

### Opportunité : `_retro` (~4 warnings éliminables)

L'inversion de séquence peut être implémentée via `.reverse` sur les tableaux :
```supercollider
// _retro A B C → Pseq([C, B, A], 1)
```

Difficulté : nécessite de collecter les éléments suivants puis les inverser.

### Opportunité : Gammes inconnues (~1 warning éliminable)

Ajouter au `scale_map.json` :
- `Cmin_minus` (si c'est une variante connue)

---

## Détail : unsupported_fn (42)

| Fonction | Count | Description | Réductible? |
|----------|-------|-------------|-------------|
| `_script` | 10 | Scripts non-MIDI | **Non** - exécution externe |
| `_rotate` | 8 | Rotation de séquence | **Oui** - `.rotate(N)` |
| `_goto` | 7 | Saut de règle | **Non** - moteur de dérivation |
| `_volumecont` | 4 | Volume continu | **Non** - pattern continu |
| `_cont` | 3 | Mode continu | **Non** - comportement global |
| `_fixed` | 3 | Mode fixe | **Non** - comportement global |
| `_pitchfixed` | 3 | Pitch fixe | **Non** - comportement global |
| `_failed` | 2 | Échec de règle | **Non** - moteur de dérivation |
| `_modcont` | 1 | Modulation continue | **Non** - pattern continu |
| `_presscont` | 1 | Aftertouch continu | **Non** - pattern continu |

### Opportunité : `_rotate(N)` (~8 warnings éliminables)

La rotation de séquence peut être implémentée via `.rotate(N)` :
```supercollider
// _rotate(2) A B C D E → Pseq([C, D, E, A, B], 1)
```

Difficulté : nécessite de collecter les éléments suivants puis les faire pivoter.

---

## Détail : context_stripped (30)

Ces warnings sont **attendus et corrects**. Ils indiquent que des symboles pass-through ont été retirés des règles multi-LHS :
```
gram#3[47] |o| |miny| --> |o1| |miny|
                                ~~~~~~
                                Pass-through stripped
```

**Non réductible** - comportement voulu.

---

## Warnings vraiment irréductibles

| Catégorie | Count | Raison |
|-----------|-------|--------|
| `Wildcard` | 55 | Nécessite moteur de dérivation |
| `_goto/_failed` | 9 | Nécessite moteur de dérivation |
| `_*cont` | 6 | Patterns continus non représentables |
| `_fixed/_pitchfixed` | 6 | Modes globaux |
| `_script (non-MIDI)` | 10 | Exécution externe |
| `context_stripped` | 30 | Comportement voulu |
| `time_sig_ignored` | 2 | Informatif |
| `homo_not_expanded` | 1 | Nécessite parser `-al.*` |
| **Subtotal irréductibles** | **~119** | |

---

## Opportunités de réduction future

| Fonction | Warnings | Effort | Impact |
|----------|----------|--------|--------|
| Parser `-al.*` pour homomorphismes | 1+ | Moyen | Permet expansion complète |
| Parser `-se.*` pour tempo/convention | ~0 | Faible | Améliore précision |
| `_retro` → `.reverse` | 4 | Faible | Simple |
| `_rotate` → `.rotate(N)` | 8 | Moyen | Nécessite buffer |
| Gammes additionnelles | 1 | Faible | Config JSON |
| **Total potentiel** | **~14** | | |

---

## Conclusion

Sur 243 warnings restants :
- **~119** sont **irréductibles** (dépendances externes, moteur de dérivation)
- **~30** sont **attendus** (context_stripped)
- **~14** sont **potentiellement réductibles** avec effort modéré
- **~80** nécessitent du travail significatif (parser fichiers ressources)

Le transpileur atteint un plateau fonctionnel. Les améliorations futures nécessitent :
1. Un parser pour les fichiers `-se.*` et `-al.*`
2. Implémentation de `_retro` et `_rotate` avec buffers
3. Extension du `scale_map.json`
