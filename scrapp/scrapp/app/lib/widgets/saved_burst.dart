import 'dart:math' as math;
import 'dart:typed_data';

import 'package:flutter/material.dart';

import '../theme/palette.dart';

/// "Saved to your collection" animation: the render pops in the middle, sparkles, then flies
/// into the collection tab. Saving never clears the workspace; this is the only feedback.
Future<void> showSavedBurst(BuildContext context, Uint8List png, {Alignment target = const Alignment(0.2, 1.05)}) async {
  final overlay = Overlay.of(context);
  late OverlayEntry entry;
  final done = ValueNotifier(false);
  entry = OverlayEntry(builder: (_) => _SavedBurst(png: png, target: target, onDone: () => done.value = true));
  overlay.insert(entry);
  while (!done.value) {
    await Future<void>.delayed(const Duration(milliseconds: 50));
  }
  entry.remove();
}

class _SavedBurst extends StatefulWidget {
  const _SavedBurst({required this.png, required this.target, required this.onDone});
  final Uint8List png;
  final Alignment target;
  final VoidCallback onDone;

  @override
  State<_SavedBurst> createState() => _SavedBurstState();
}

class _SavedBurstState extends State<_SavedBurst> with SingleTickerProviderStateMixin {
  late final AnimationController c = AnimationController(vsync: this, duration: const Duration(milliseconds: 1600))
    ..forward().whenComplete(widget.onDone);

  @override
  void dispose() {
    c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return IgnorePointer(
      child: AnimatedBuilder(
        animation: c,
        builder: (context, _) {
          final t = c.value;
          final pop = Curves.elasticOut.transform((t / 0.45).clamp(0, 1));
          final fly = Curves.easeInCubic.transform(((t - 0.55) / 0.45).clamp(0, 1));
          final align = Alignment.lerp(Alignment.center, widget.target, fly)!;
          final scale = (0.2 + 0.8 * pop) * (1 - 0.85 * fly);
          return Stack(children: [
            Positioned.fill(child: ColoredBox(color: Palette.ink.withValues(alpha: 0.18 * (1 - fly)))),
            Align(
              alignment: align,
              child: Transform.rotate(
                angle: -0.06 + 0.06 * fly,
                child: Transform.scale(
                  scale: scale,
                  child: Column(mainAxisSize: MainAxisSize.min, children: [
                    Container(
                      width: 220,
                      padding: const EdgeInsets.fromLTRB(10, 10, 10, 30),
                      decoration: BoxDecoration(color: Palette.card, borderRadius: BorderRadius.circular(6),
                          boxShadow: [BoxShadow(color: Palette.ink.withValues(alpha: 0.3), blurRadius: 16, offset: const Offset(0, 8))]),
                      child: Image.memory(widget.png, fit: BoxFit.cover),
                    ),
                    Opacity(
                      opacity: (1 - fly),
                      child: Container(
                        margin: const EdgeInsets.only(top: 12),
                        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
                        decoration: BoxDecoration(color: Palette.sage, borderRadius: BorderRadius.circular(20)),
                        child: const Text('Saved to your collection', style: TextStyle(fontWeight: FontWeight.w900, color: Palette.ink)),
                      ),
                    ),
                  ]),
                ),
              ),
            ),
            ..._sparkles(t),
          ]);
        },
      ),
    );
  }

  List<Widget> _sparkles(double t) {
    final p = ((t - 0.08) / 0.5).clamp(0.0, 1.0);
    if (p <= 0 || p >= 1) return const [];
    return List.generate(14, (i) {
      final a = i / 14 * math.pi * 2;
      final r = 90 + 110 * Curves.easeOut.transform(p);
      return Align(
        alignment: Alignment.center,
        child: Transform.translate(
          offset: Offset(math.cos(a) * r, math.sin(a) * r),
          child: Opacity(
            opacity: 1 - p,
            child: Icon(i.isEven ? Icons.star_rounded : Icons.circle, size: i.isEven ? 18 : 8, color: i % 3 == 0 ? Palette.teal : Palette.sage),
          ),
        ),
      );
    });
  }
}
