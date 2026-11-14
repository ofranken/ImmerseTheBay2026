import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../theme/palette.dart';

/// Everything related to 3D / mesh generation wears this plush, grass-like fuzz.
const _fuzz = AssetImage('assets/web/textures/fuzz_grass.jpg');

class FuzzyPanel extends StatelessWidget {
  const FuzzyPanel({super.key, required this.child, this.radius = 26, this.padding = const EdgeInsets.all(18), this.onTap});
  final Widget child;
  final double radius;
  final EdgeInsets padding;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final r = BorderRadius.circular(radius);
    return CustomPaint(
      // Strands drawn just outside the clip give the silhouette its fuzz.
      foregroundPainter: _FuzzEdgePainter(radius: radius),
      child: Container(
        decoration: BoxDecoration(
          borderRadius: r,
          boxShadow: [BoxShadow(color: Palette.sageDeep.withValues(alpha: 0.45), blurRadius: 14, offset: const Offset(0, 6))],
        ),
        child: Material(
          borderRadius: r,
          clipBehavior: Clip.antiAlias,
          color: Palette.sage,
          child: Ink(
            decoration: const BoxDecoration(image: DecorationImage(image: _fuzz, repeat: ImageRepeat.repeat, scale: 1.6)),
            child: InkWell(
              onTap: onTap,
              child: DecoratedBox(
                // Inner glow: lighter top, deeper bottom, like plush catching light.
                decoration: BoxDecoration(
                  gradient: LinearGradient(
                    begin: Alignment.topCenter,
                    end: Alignment.bottomCenter,
                    colors: [Colors.white.withValues(alpha: 0.16), Colors.transparent, Palette.ink.withValues(alpha: 0.18)],
                  ),
                ),
                child: Padding(padding: padding, child: DefaultTextStyle.merge(style: fuzzText, child: IconTheme.merge(data: const IconThemeData(color: Palette.card), child: child))),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// Cream, bold, with an embossed shadow: readable on the textured surface.
const fuzzText = TextStyle(
  color: Palette.card,
  fontWeight: FontWeight.w900,
  shadows: [Shadow(color: Color(0x995C3A26), offset: Offset(0, 1.5), blurRadius: 2)],
);

class FuzzyButton extends StatelessWidget {
  const FuzzyButton({super.key, required this.label, required this.icon, this.onPressed, this.busy = false});
  final String label;
  final IconData icon;
  final VoidCallback? onPressed;
  final bool busy;

  @override
  Widget build(BuildContext context) => Semantics(
        button: true,
        label: label,
        child: Opacity(
          opacity: onPressed == null ? 0.55 : 1,
          child: FuzzyPanel(
            radius: 40,
            padding: const EdgeInsets.symmetric(horizontal: 22, vertical: 14),
            onTap: busy ? null : onPressed,
            child: Row(mainAxisSize: MainAxisSize.min, mainAxisAlignment: MainAxisAlignment.center, children: [
              busy
                  ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2.5, color: Palette.card))
                  : Icon(icon, size: 22, shadows: fuzzText.shadows),
              const SizedBox(width: 10),
              Flexible(child: Text(label, style: const TextStyle(fontSize: 16))),
            ]),
          ),
        ),
      );
}

/// A fuzzy progress bar for Meshy jobs.
class FuzzyProgress extends StatelessWidget {
  const FuzzyProgress({super.key, required this.value});
  final double value;

  @override
  Widget build(BuildContext context) => SizedBox(
        height: 16,
        child: Stack(children: [
          Container(decoration: BoxDecoration(color: Palette.paper, borderRadius: BorderRadius.circular(10), border: Border.all(color: Palette.inkSoft.withValues(alpha: 0.3)))),
          FractionallySizedBox(
            widthFactor: value.clamp(0.04, 1.0),
            child: ClipRRect(
              borderRadius: BorderRadius.circular(10),
              child: const DecoratedBox(decoration: BoxDecoration(image: DecorationImage(image: _fuzz, repeat: ImageRepeat.repeat, scale: 2.5)), child: SizedBox.expand()),
            ),
          ),
        ]),
      );
}

class _FuzzEdgePainter extends CustomPainter {
  _FuzzEdgePainter({required this.radius});
  final double radius;

  @override
  void paint(Canvas canvas, Size size) {
    final rrect = RRect.fromRectAndRadius(Offset.zero & size, Radius.circular(radius));
    final path = Path()..addRRect(rrect);
    final rnd = math.Random(size.width.toInt() * 31 + size.height.toInt());
    final paint = Paint()
      ..strokeCap = StrokeCap.round
      ..strokeWidth = 1.3;
    const shades = [Color(0xFFA3B18A), Color(0xFF8E9C74), Color(0xFFB9C59F), Color(0xFF7F8D66)];
    for (final metric in path.computeMetrics()) {
      for (double d = 0; d < metric.length; d += 1.6) {
        final t = metric.getTangentForOffset(d);
        if (t == null) continue;
        final normal = Offset(t.vector.dy, -t.vector.dx); // outward for a clockwise rrect
        final angle = (rnd.nextDouble() - 0.5) * 0.9;
        final dir = Offset(normal.dx * math.cos(angle) - normal.dy * math.sin(angle), normal.dx * math.sin(angle) + normal.dy * math.cos(angle));
        final len = 1.5 + rnd.nextDouble() * 3.5;
        final start = t.position - normal * 1.5;
        paint.color = shades[rnd.nextInt(shades.length)];
        canvas.drawLine(start, start + dir * len, paint);
      }
    }
  }

  @override
  bool shouldRepaint(covariant _FuzzEdgePainter old) => old.radius != radius;
}
