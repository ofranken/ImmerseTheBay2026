import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models.dart';
import '../state/library.dart';
import '../theme/palette.dart';
import '../widgets/paper.dart';
import 'sticker_screen.dart';

/// The untouched original photo plus every sticker cut from it. Tap the photo to cut a new one.
class CaptureScreen extends StatefulWidget {
  const CaptureScreen({super.key, required this.captureId});
  final String captureId;
  @override
  State<CaptureScreen> createState() => _CaptureScreenState();
}

class _CaptureScreenState extends State<CaptureScreen> {
  Capture? capture;
  bool cutting = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final c = await context.read<Library>().capture(widget.captureId);
    if (!mounted) return;
    setState(() => capture = c);
    if (c.processing) Future.delayed(const Duration(seconds: 2), () => mounted ? _load() : null);
  }

  Future<void> _cut(TapUpDetails d, BoxConstraints box) async {
    final c = capture!;
    if (c.width == 0 || cutting) return;
    // Map the tap through BoxFit.contain back to normalised image coordinates.
    final scale = (box.maxWidth / c.width).clamp(0, box.maxHeight / c.height).toDouble();
    final w = c.width * scale, h = c.height * scale;
    final ox = (box.maxWidth - w) / 2, oy = (box.maxHeight - h) / 2;
    final x = (d.localPosition.dx - ox) / w, y = (d.localPosition.dy - oy) / h;
    if (x < 0 || x > 1 || y < 0 || y > 1) return;
    setState(() => cutting = true);
    try {
      await context.read<Library>().cutAt(c.id, x, y);
      await _load();
      if (mounted) toast(context, 'New sticker cut!');
    } catch (e) {
      if (mounted) toast(context, '$e');
    } finally {
      if (mounted) setState(() => cutting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = capture;
    return Scaffold(
      appBar: AppBar(title: const Text('ORIGINAL')),
      body: PaperBackground(
        child: c == null
            ? const Center(child: CircularProgressIndicator())
            : ListView(padding: const EdgeInsets.all(16), children: [
                PaperCard(
                  padding: const EdgeInsets.all(8),
                  child: AspectRatio(
                    aspectRatio: c.width > 0 ? c.width / c.height : 3 / 4,
                    child: LayoutBuilder(builder: (context, box) => GestureDetector(
                      onTapUp: (d) => _cut(d, box),
                      child: Stack(fit: StackFit.expand, children: [
                        ClipRRect(borderRadius: BorderRadius.circular(14), child: Image.network(c.originalUrl ?? '', fit: BoxFit.contain)),
                        if (cutting) const ColoredBox(color: Color(0x553C2A1E), child: Center(child: CircularProgressIndicator(color: Palette.card))),
                      ]),
                    )),
                  ),
                ),
                const SizedBox(height: 10),
                Wrap(spacing: 8, runSpacing: 8, children: [
                  LocationChip(place: c.placeName, lat: c.lat, lng: c.lng),
                  Pill(label: 'via ${c.trigger}', icon: Icons.mic_none_rounded, color: Palette.paper),
                  if (c.capturedAt != null) Pill(label: _fmt(c.capturedAt!), icon: Icons.schedule_rounded, color: Palette.paper),
                ]),
                const SizedBox(height: 6),
                const Text('Tap anything in the photo to cut it into a sticker.', style: TextStyle(color: Palette.inkSoft)),
                SectionTitle('Stickers (${c.stickers.length})'),
                if (c.processing) const LinearProgressIndicator(),
                Wrap(spacing: 12, runSpacing: 12, children: [
                  for (final s in c.stickers)
                    GestureDetector(
                      onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => StickerScreen(sticker: s))),
                      child: PaperCard(padding: const EdgeInsets.all(8), child: StickerImage(url: s.imageUrl, size: 96, heroTag: 'st-${s.id}')),
                    ),
                ]),
              ]),
      ),
    );
  }

  String _fmt(DateTime d) {
    final l = d.toLocal();
    return '${l.month}/${l.day}/${l.year} ${l.hour}:${l.minute.toString().padLeft(2, '0')}';
  }
}
