import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models.dart';
import '../services/ar_bridge.dart';
import '../state/app_state.dart';
import '../state/library.dart';
import '../state/social.dart';
import '../theme/palette.dart';
import '../theme/theme.dart';
import '../widgets/fuzzy.dart';
import '../widgets/paper.dart';
import 'capture_screen.dart';
import 'collage_editor_screen.dart';
import 'studio_screen.dart';

class StickerScreen extends StatelessWidget {
  const StickerScreen({super.key, required this.sticker});
  final Sticker sticker;

  @override
  Widget build(BuildContext context) {
    final me = context.read<AppState>().user?.id;
    final mine = sticker.ownerId == me;
    return Scaffold(
      appBar: AppBar(title: Text(sticker.title.toUpperCase())),
      body: PaperBackground(
        child: ListView(padding: const EdgeInsets.all(18), children: [
          Center(child: StickerImage(url: sticker.imageUrl, size: 260, heroTag: 'st-${sticker.id}')),
          const SizedBox(height: 14),
          Center(child: LocationChip(place: sticker.placeName, lat: sticker.lat, lng: sticker.lng)),
          const SizedBox(height: 20),
          if (mine) ...[
            ScrappButton(label: 'Send to a friend', icon: Icons.send_rounded, expand: true, onPressed: () => showShareSheet(context, sticker)),
            const SizedBox(height: 10),
          ],
          ScrappButton(
            label: 'See it in AR',
            icon: Icons.view_in_ar_rounded,
            style: ScrappButtonStyle.quiet,
            expand: true,
            onPressed: () => ArBridge.open(
              title: sticker.title,
              instructions: 'Tap a surface to place your sticker',
              items: [ArItem(id: sticker.id, imageUrl: sticker.imageUrl!, anchor: AnchorSpec(mode: 'surface'), title: sticker.title)],
            ),
          ),
          const SizedBox(height: 10),
          ScrappButton(
            label: 'Add to a new collage',
            icon: Icons.layers_rounded,
            style: ScrappButtonStyle.quiet,
            expand: true,
            onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => CollageEditorScreen(seedStickers: [sticker]))),
          ),
          if (mine) ...[
            const SizedBox(height: 10),
            ScrappButton(
              label: 'Open original photo',
              icon: Icons.photo_rounded,
              style: ScrappButtonStyle.quiet,
              expand: true,
              onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => CaptureScreen(captureId: sticker.captureId))),
            ),
            const SizedBox(height: 22),
            _GrowTo3D(sticker: sticker),
            const SizedBox(height: 22),
            TextButton.icon(
              icon: const Icon(Icons.delete_outline_rounded, color: Palette.danger),
              label: const Text('Delete sticker', style: TextStyle(color: Palette.danger, fontWeight: FontWeight.w800)),
              onPressed: () async {
                await context.read<Library>().deleteSticker(sticker.id);
                if (context.mounted) Navigator.pop(context);
              },
            ),
          ],
        ]),
      ),
    );
  }
}

/// Send a sticker to friends and decide how it anchors in their world.
Future<void> showShareSheet(BuildContext context, Sticker sticker) async {
  final social = context.read<Social>();
  if (social.friends.isEmpty) await social.refreshFriends();
  if (!context.mounted) return;
  await showModalBottomSheet(
    context: context,
    isScrollControlled: true,
    backgroundColor: Palette.card,
    shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(28))),
    builder: (_) => _ShareSheet(sticker: sticker),
  );
}

class _ShareSheet extends StatefulWidget {
  const _ShareSheet({required this.sticker});
  final Sticker sticker;
  @override
  State<_ShareSheet> createState() => _ShareSheetState();
}

class _ShareSheetState extends State<_ShareSheet> {
  final to = <String>{};
  final anchor = AnchorSpec(mode: 'object', objectClass: 'apple', animation: 'wiggle');
  final message = TextEditingController();
  bool busy = false;

  @override
  Widget build(BuildContext context) {
    final friends = context.watch<Social>().friends;
    return Padding(
      padding: EdgeInsets.fromLTRB(20, 16, 20, 20 + MediaQuery.of(context).viewInsets.bottom),
      child: SingleChildScrollView(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
          Text('SEND STICKER', style: ScrappType.display(28)),
          const SizedBox(height: 12),
          const Text('To', style: TextStyle(fontWeight: FontWeight.w900)),
          const SizedBox(height: 6),
          if (friends.isEmpty) const Text('Add friends in the Friends tab first.', style: TextStyle(color: Palette.inkSoft)),
          Wrap(spacing: 8, runSpacing: 8, children: [
            for (final f in friends)
              FilterChip(label: Text(f.displayName), selected: to.contains(f.id), onSelected: (v) => setState(() => v ? to.add(f.id) : to.remove(f.id))),
          ]),
          const SizedBox(height: 16),
          const Text('Where it appears for them', style: TextStyle(fontWeight: FontWeight.w900)),
          const SizedBox(height: 6),
          Wrap(spacing: 8, runSpacing: 8, children: [
            for (final (mode, label) in [('object', 'On a kind of object'), ('surface', 'Any surface'), ('image', 'On the exact thing'), ('geo', 'Right here (GPS)')])
              ChoiceChip(label: Text(label), selected: anchor.mode == mode, onSelected: (_) => setState(() => anchor.mode = mode)),
          ]),
          if (anchor.mode == 'object') ...[
            const SizedBox(height: 10),
            DropdownButtonFormField<String>(
              value: anchor.objectClass,
              decoration: const InputDecoration(labelText: 'They hold up a…'),
              items: [for (final c in anchorObjectClasses) DropdownMenuItem(value: c, child: Text(c))],
              onChanged: (v) => setState(() => anchor.objectClass = v),
            ),
          ],
          if (anchor.mode == 'geo') const Padding(padding: EdgeInsets.only(top: 6), child: Text('Uses where this sticker was captured.', style: TextStyle(color: Palette.inkSoft))),
          if (anchor.mode == 'image') const Padding(padding: EdgeInsets.only(top: 6), child: Text('Their camera finds the original object from your photo.', style: TextStyle(color: Palette.inkSoft))),
          const SizedBox(height: 14),
          const Text('Animation', style: TextStyle(fontWeight: FontWeight.w900)),
          const SizedBox(height: 6),
          Wrap(spacing: 8, children: [
            for (final a in ['wiggle', 'bob', 'spin', 'pop', 'none'])
              ChoiceChip(label: Text(a), selected: anchor.animation == a, onSelected: (_) => setState(() => anchor.animation = a)),
          ]),
          const SizedBox(height: 14),
          TextField(controller: message, decoration: const InputDecoration(labelText: 'Message (optional)', hintText: 'ha ha look at your apple')),
          const SizedBox(height: 18),
          ScrappButton(
            label: 'Send',
            icon: Icons.send_rounded,
            expand: true,
            busy: busy,
            onPressed: to.isEmpty
                ? null
                : () async {
                    setState(() => busy = true);
                    final s = widget.sticker;
                    if (anchor.mode == 'geo') {
                      anchor.lat = s.lat;
                      anchor.lng = s.lng;
                    }
                    try {
                      final n = await context.read<Social>().share(kind: 'sticker', itemId: s.id, to: to.toList(), anchor: anchor, message: message.text);
                      if (context.mounted) {
                        Navigator.pop(context);
                        toast(context, 'Sent to $n ${n == 1 ? 'friend' : 'friends'}');
                      }
                    } catch (e) {
                      if (context.mounted) toast(context, '$e');
                    } finally {
                      if (mounted) setState(() => busy = false);
                    }
                  },
          ),
        ]),
      ),
    );
  }
}


/// Sticker -> 3D (Meshy). Shows the state of this sticker's model: start, growing, ready (view) or failed (retry).
class _GrowTo3D extends StatelessWidget {
  const _GrowTo3D({required this.sticker});
  final Sticker sticker;

  MeshJob? _job(Library lib) {
    for (final m in lib.meshes) {
      if (m.stickerId == sticker.id && !m.failed) return m; // newest first; a failed attempt doesn't block a retry
    }
    return null;
  }

  Future<void> _start(BuildContext context) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Make this 3D?'),
        content: const Text('The sticker picture is sent to Meshy, a third-party service, to build a 3D model. '
            'It takes a few minutes and uses the project\'s Meshy credits.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
          TextButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Make it 3D')),
        ],
      ),
    );
    if (ok != true || !context.mounted) return;
    try {
      await context.read<Library>().meshFromSticker(sticker.id);
      if (context.mounted) toast(context, 'Growing a 3D model. It shows up here and in Studio → 3D.');
    } catch (e) {
      if (context.mounted) toast(context, '$e');
    }
  }

  @override
  Widget build(BuildContext context) {
    final job = _job(context.watch<Library>());
    if (job == null) {
      return FuzzyButton(label: 'Grow it into 3D (Meshy)', icon: Icons.grass_rounded, onPressed: () => _start(context));
    }
    if (job.done) {
      return FuzzyButton(
        label: 'View the 3D model',
        icon: Icons.view_in_ar_rounded,
        onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => MeshPreviewScreen(mesh: job))),
      );
    }
    return Column(children: [
      FuzzyButton(label: 'Growing 3D… ${(job.overall * 100).round()}%', icon: Icons.grass_rounded, busy: true, onPressed: null),
      const SizedBox(height: 8),
      FuzzyProgress(value: job.overall),
    ]);
  }
}
