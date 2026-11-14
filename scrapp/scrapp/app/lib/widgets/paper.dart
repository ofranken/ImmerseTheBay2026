import 'package:flutter/material.dart';

import '../theme/palette.dart';
import '../theme/theme.dart';

const _grain = AssetImage('assets/web/textures/paper_grain.png');

/// Page background: warm cream with a tiled paper-grain overlay.
class PaperBackground extends StatelessWidget {
  const PaperBackground({super.key, required this.child});
  final Widget child;

  @override
  Widget build(BuildContext context) => DecoratedBox(
        decoration: const BoxDecoration(
          color: Palette.paper,
          image: DecorationImage(image: _grain, repeat: ImageRepeat.repeat, scale: 2),
        ),
        child: child,
      );
}

/// Soft, slightly raised paper card (neumorphic light/dark shadow pair from the sage reference).
class PaperCard extends StatelessWidget {
  const PaperCard({super.key, required this.child, this.padding = const EdgeInsets.all(16), this.onTap, this.color = Palette.card, this.radius = 22});
  final Widget child;
  final EdgeInsets padding;
  final VoidCallback? onTap;
  final Color color;
  final double radius;

  @override
  Widget build(BuildContext context) {
    final r = BorderRadius.circular(radius);
    return Container(
      decoration: BoxDecoration(
        borderRadius: r,
        boxShadow: [
          BoxShadow(color: Colors.white.withValues(alpha: 0.7), offset: const Offset(-3, -3), blurRadius: 8),
          BoxShadow(color: Palette.inkSoft.withValues(alpha: 0.16), offset: const Offset(4, 5), blurRadius: 12),
        ],
      ),
      child: Material(
        color: color,
        borderRadius: r,
        clipBehavior: Clip.antiAlias,
        child: Ink(
          decoration: const BoxDecoration(image: DecorationImage(image: _grain, repeat: ImageRepeat.repeat, scale: 2)),
          child: InkWell(onTap: onTap, child: Padding(padding: padding, child: child)),
        ),
      ),
    );
  }
}

enum ScrappButtonStyle { primary, quiet, sage, danger }

class ScrappButton extends StatelessWidget {
  const ScrappButton({super.key, required this.label, this.icon, this.onPressed, this.style = ScrappButtonStyle.primary, this.expand = false, this.busy = false});
  final String label;
  final IconData? icon;
  final VoidCallback? onPressed;
  final ScrappButtonStyle style;
  final bool expand;
  final bool busy;

  @override
  Widget build(BuildContext context) {
    final (bg, fg) = switch (style) {
      ScrappButtonStyle.primary => (Palette.teal, Palette.ink),
      ScrappButtonStyle.quiet => (Palette.card, Palette.ink),
      ScrappButtonStyle.sage => (Palette.sage, Palette.ink),
      ScrappButtonStyle.danger => (Palette.danger, Colors.white),
    };
    final child = Row(
      mainAxisSize: expand ? MainAxisSize.max : MainAxisSize.min,
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        if (busy)
          SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2.4, color: fg))
        else if (icon != null)
          Icon(icon, size: 20, color: fg),
        if (busy || icon != null) const SizedBox(width: 8),
        Flexible(child: Text(label, overflow: TextOverflow.ellipsis, style: TextStyle(color: fg, fontWeight: FontWeight.w800, fontSize: 16))),
      ],
    );
    return Semantics(
      button: true,
      label: label,
      child: DecoratedBox(
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(40),
          boxShadow: [BoxShadow(color: Palette.inkSoft.withValues(alpha: onPressed == null ? 0 : 0.22), offset: const Offset(0, 3))],
        ),
        child: Material(
          color: onPressed == null ? bg.withValues(alpha: 0.5) : bg,
          shape: StadiumBorder(side: BorderSide(color: Palette.inkSoft.withValues(alpha: 0.25))),
          clipBehavior: Clip.antiAlias,
          child: InkWell(
            onTap: busy ? null : onPressed,
            child: ConstrainedBox(
              constraints: const BoxConstraints(minHeight: 52),
              child: Padding(padding: const EdgeInsets.symmetric(horizontal: 22, vertical: 12), child: child),
            ),
          ),
        ),
      ),
    );
  }
}

class Pill extends StatelessWidget {
  const Pill({super.key, required this.label, this.icon, this.color = Palette.card, this.fg = Palette.ink});
  final String label;
  final IconData? icon;
  final Color color;
  final Color fg;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
        decoration: BoxDecoration(color: color, borderRadius: BorderRadius.circular(30), border: Border.all(color: Palette.inkSoft.withValues(alpha: 0.25))),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          if (icon != null) ...[Icon(icon, size: 16, color: fg), const SizedBox(width: 6)],
          Text(label, style: TextStyle(color: fg, fontWeight: FontWeight.w800, fontSize: 13)),
        ]),
      );
}

class LocationChip extends StatelessWidget {
  const LocationChip({super.key, this.place, this.lat, this.lng});
  final String? place;
  final double? lat;
  final double? lng;

  @override
  Widget build(BuildContext context) {
    final label = (place != null && place!.isNotEmpty)
        ? place!
        : (lat != null ? '${lat!.toStringAsFixed(4)}, ${lng!.toStringAsFixed(4)}' : 'No location');
    return Pill(label: label, icon: Icons.place_rounded, color: Palette.paper);
  }
}

class SectionTitle extends StatelessWidget {
  const SectionTitle(this.text, {super.key, this.trailing});
  final String text;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.fromLTRB(4, 18, 4, 10),
        child: Row(children: [
          Expanded(child: Text(text.toUpperCase(), style: ScrappType.display(24))),
          if (trailing != null) trailing!,
        ]),
      );
}

class EmptyNote extends StatelessWidget {
  const EmptyNote({super.key, required this.icon, required this.title, required this.body});
  final IconData icon;
  final String title;
  final String body;

  @override
  Widget build(BuildContext context) => PaperCard(
        child: Row(children: [
          Icon(icon, size: 36, color: Palette.inkSoft),
          const SizedBox(width: 14),
          Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(title, style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 17)),
            const SizedBox(height: 4),
            Text(body, style: const TextStyle(color: Palette.inkSoft)),
          ])),
        ]),
      );
}

/// A die-cut sticker image with a soft paper shadow under it.
class StickerImage extends StatelessWidget {
  const StickerImage({super.key, required this.url, this.size = 120, this.heroTag});
  final String? url;
  final double size;
  final String? heroTag;

  @override
  Widget build(BuildContext context) {
    Widget img = url == null
        ? Icon(Icons.image_not_supported_outlined, size: size * 0.4, color: Palette.inkSoft)
        : Image.network(url!, width: size, height: size, fit: BoxFit.contain,
            errorBuilder: (_, __, ___) => Icon(Icons.broken_image_outlined, size: size * 0.4, color: Palette.inkSoft),
            loadingBuilder: (_, child, p) => p == null ? child : SizedBox(width: size, height: size, child: const Center(child: CircularProgressIndicator(strokeWidth: 2))));
    img = DecoratedBox(
      decoration: BoxDecoration(boxShadow: [BoxShadow(color: Palette.inkSoft.withValues(alpha: 0.18), blurRadius: 10, offset: const Offset(2, 5))]),
      child: SizedBox(width: size, height: size, child: Center(child: img)),
    );
    return heroTag == null ? img : Hero(tag: heroTag!, child: img);
  }
}

void toast(BuildContext context, String msg) {
  ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg), behavior: SnackBarBehavior.floating));
}
