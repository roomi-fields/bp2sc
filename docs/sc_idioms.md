# SuperCollider Patterns — Guide pour utilisateurs BP3

Ce guide présente les concepts SuperCollider essentiels pour comprendre et modifier les fichiers `.scd` générés par bp2sc.

---

## 1. SuperCollider en 5 minutes

SuperCollider est un environnement de synthèse audio et de composition algorithmique. Il comporte :

- **sclang** : le langage de programmation (interpréteur)
- **scsynth** : le serveur audio (synthèse en temps réel)

```supercollider
// Démarrer le serveur audio
s.boot;

// Créer un SynthDef (définition d'instrument)
SynthDef(\simple, {
    |out=0, freq=440, amp=0.1, gate=1|
    var sig = SinOsc.ar(freq) * amp;
    var env = EnvGen.kr(Env.adsr, gate, doneAction: 2);
    Out.ar(out, sig * env ! 2);
}).add;

// Jouer une note
Synth(\simple, [\freq, 440, \amp, 0.2]);

// Arrêter tout : Cmd+. (Mac) ou Ctrl+. (Linux/Windows)
```

---

## 2. Patterns essentiels

Les **Patterns** sont des templates qui génèrent des séquences de valeurs. Ils sont le cœur du système de composition algorithmique de SC.

### Pseq — Séquence ordonnée

```supercollider
// Jouer les notes 60, 62, 64 une fois
Pseq([60, 62, 64], 1)

// Jouer en boucle infinie
Pseq([60, 62, 64], inf)
```

**Mapping BP3** : une séquence de notes dans un RHS → `Pseq([...])`.

### Prand — Choix aléatoire (uniforme)

```supercollider
// Choisir au hasard parmi 3 motifs, 8 fois
Prand([60, 64, 67], 8)
```

**Mapping BP3** : mode RND sans poids → `Prand`.

### Pwrand — Choix aléatoire pondéré

```supercollider
// 60 a 50% de chance, 64 a 30%, 67 a 20%
Pwrand([60, 64, 67], [0.5, 0.3, 0.2], 8)

// .normalizeSum normalise automatiquement les poids
Pwrand([60, 64, 67], [50, 30, 20].normalizeSum, 8)
```

**Mapping BP3** : mode RND avec poids `<N>` → `Pwrand([...], [...].normalizeSum)`.

### Ppar — Voix parallèles

```supercollider
// Deux voix simultanées
Ppar([
    Pbind(\midinote, Pseq([60, 64, 67], 4), \dur, 0.5),
    Pbind(\midinote, Pseq([48, 52, 55], 4), \dur, 0.75)
])
```

**Mapping BP3** : expression polymétrique multi-voix `{seq1, seq2}` → `Ppar`.

### Pn — Répétition

```supercollider
// Répéter un pattern 3 fois
Pn(Pseq([60, 62, 64], 1), 3)
```

### Pbind — Liaison clé-valeur (événements)

```supercollider
// Créer des événements musicaux
Pbind(
    \instrument, \default,
    \midinote, Pseq([60, 62, 64, 65, 67], inf),
    \dur, 0.25,
    \amp, 0.3
).play;
```

Clés importantes :

| Clé | Fonction | Exemple |
|-----|----------|---------|
| `\midinote` | Hauteur MIDI (0-127) | `60` = do central |
| `\dur` | Durée jusqu'au prochain event (en beats) | `0.25` = double croche |
| `\amp` | Amplitude (0-1) | `0.5` = mezzo forte |
| `\instrument` | Nom du SynthDef | `\default` |
| `\ctranspose` | Transposition chromatique | `7` = quinte |
| `\mtranspose` | Transposition modale | `2` = tierce dans l'échelle |
| `\stretch` | Étirement temporel | `2` = deux fois plus lent |
| `\pan` | Panoramique stéréo (-1 à 1) | `0` = centre |
| `\detune` | Désaccordage en Hz | `5.0` |
| `\legato` | Fraction de dur pour le sustain | `0.8` |

### Rest — Silence

```supercollider
// Un silence dans une séquence
Pseq([60, 62, Rest(), 64], inf)
```

**Mapping BP3** : `-` (silence déterminé) → `Rest()`.

---

## 3. Pdef / Pbindef — Le cœur du morphing live

### Pdef — Pattern nommé global

`Pdef` crée un pattern référencé par un nom global. Remplacer le contenu d'un Pdef met à jour toutes les références en temps réel.

```supercollider
// Définir et jouer
Pdef(\melody, Pbind(
    \midinote, Pseq([60, 64, 67, 72], inf),
    \dur, 0.25
)).play;

// Remplacer le contenu — la musique change immédiatement
Pdef(\melody, Pbind(
    \midinote, Pseq([72, 71, 67, 64, 60], inf),
    \dur, 0.15
));

// Arrêter
Pdef(\melody).stop;
```

### Pbindef — Modification incrémentale

`Pbindef` modifie des clés individuelles sans remplacer tout le pattern :

```supercollider
// Créer et jouer
Pbindef(\riff, \midinote, Pseq([60, 63, 67], inf), \dur, 0.25).play;

// Changer seulement la durée
Pbindef(\riff, \dur, 0.125);

// Ajouter une transposition
Pbindef(\riff, \ctranspose, 5);

// Retirer la transposition
Pbindef(\riff, \ctranspose, nil);
```

### Quantification du swap

Par défaut, le remplacement se fait au prochain beat. On peut contrôler le timing :

```supercollider
Pdef(\x).quant = 0;    // immédiat
Pdef(\x).quant = 4;    // au prochain multiple de 4 beats
Pdef(\x).quant = [8, 0, 0, 1];  // quantifié à 8 beats avec fast-forward
```

### Crossfade

```supercollider
Pdef(\x).fadeTime = 4;  // fondu enchaîné sur 4 beats
Pdef(\x, nouveauPattern);  // le crossfade se fait automatiquement
```

---

## 4. Recettes de morphing pour patterns bp2sc

Après avoir généré un `.scd` avec bp2sc, voici les transformations courantes :

### Remplacer un motif

```supercollider
// Le motif original (généré par bp2sc)
Pdef(\Tihai, Pseq([...], 1));

// Votre nouveau motif
Pdef(\Tihai, Pbind(
    \midinote, Pseq([60, 62, 64, 65, 67, 69, 71, 72], 1),
    \dur, 0.2,
    \amp, 0.4
));
```

### Transposer globalement

```supercollider
// Ajouter une transposition à un pattern existant
Pbindef(\S, \ctranspose, 7);  // quinte

// Transposition modale (dans l'échelle)
Pbindef(\S, \mtranspose, 2);  // tierce modale
```

### Changer la densité rythmique

```supercollider
Pbindef(\cell, \dur, 0.125);  // double vitesse
Pbindef(\cell, \dur, 0.5);    // moitié vitesse
```

### Changer le tempo global

```supercollider
TempoClock.default.tempo = 120 / 60;  // 120 BPM
TempoClock.default.tempo = 88 / 60;   // 88 BPM (original)
```

### Ajouter du mouvement spatial

```supercollider
Pbindef(\melody, \pan, Pwhite(-1.0, 1.0));  // panoramique aléatoire
Pbindef(\melody, \pan, Pseq([-0.8, 0.8], inf));  // ping-pong
```

### Changer la dynamique

```supercollider
Pbindef(\phrase, \amp, Pseq([0.1, 0.3, 0.5, 0.3], inf));  // crescendo/decrescendo
```

### Superposer des couches

```supercollider
// Ajouter une voix de basse sous le pattern existant
Pdef(\layered, Ppar([
    Pdef(\S),  // le pattern bp2sc original
    Pbind(
        \midinote, Pseq([36, 43, 36, 48], inf),
        \dur, 1,
        \amp, 0.2
    )
])).play;
```

---

## 5. Debugging

### Voir le contenu d'un Pdef

```supercollider
Pdef(\melody).source.postln;
```

### Tracer les événements

```supercollider
Pdef(\melody).trace.play;  // affiche chaque event dans la console
```

### Tester un stream manuellement

```supercollider
x = Pdef(\melody).asStream;
x.next(Event.default).postln;  // prochain événement
x.next(Event.default).postln;  // suivant
```

### Lister tous les Pdefs actifs

```supercollider
Pdef.all.keys.do(_.postln);
```

### Nettoyer

```supercollider
Pdef.removeAll;  // supprimer tous les Pdefs
CmdPeriod.run;   // arrêter tout
```
