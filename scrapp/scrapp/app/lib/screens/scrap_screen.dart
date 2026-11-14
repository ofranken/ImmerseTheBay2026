import 'dart:io';

import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'package:provider/provider.dart';

import '../services/glasses_bridge.dart';
import '../state/glasses_state.dart';
import '../state/library.dart';
import '../theme/palette.dart';
import '../theme/theme.dart';
import '../widgets/paper.dart';
import 'capture_screen.dart';
import 'settings_screen.dart';

class ScrapScreen extends StatelessWidget {
  const ScrapScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final g = context.watch<GlassesState>();
    final lib = context.watch<Library>();
    return RefreshIndicator(
      onRefresh: () async {
        await g.refreshStatus();
        await lib.refreshCaptures();
      },
      child: ListView(padding: const EdgeInsets.fromLTRB(18, 8, 18, 32), children: [
        Row(children: [
          Text('Scrapp', style: ScrappType.wordmark(44)),
          const Spacer(),
          IconButton(
            tooltip: 'Settings',
            icon: const Icon(Icons.tune_rounded),
            onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const SettingsScreen())),
          ),
        ]),
        _GlassesCard(g: g),
        if (g.activeHunt != null) ...[
          const SizedBox(height: 14),
          PaperCard(
            color: Palette.sage,
            child: Row(children: [
              const Icon(Icons.travel_explore_rounded, size: 30),
              const SizedBox(width: 12),
              Expanded(child: Text('Hunt on: ${g.activeHunt!.title}\n${g.activeHunt!.foundCount}/${g.activeHunt!.total} found. "Scrapbook that" checks finds.',
                  style: const TextStyle(fontWeight: FontWeight.w800))),
              IconButton(tooltip: 'End hunt', icon: const Icon(Icons.close_rounded), onPressed: () => g.setActiveHunt(null)),
            ]),
          ),
        ],
        const SizedBox(height: 14),
        Row(children: [
          Expanded(child: ScrappButton(label: 'Scrapbook now', icon: Icons.auto_awesome_rounded, expand: true,
              onPressed: g.armed ? () => GlassesBridge.captureNow() : null)),
          const SizedBox(width: 10),
          ScrappButton(label: 'Photo', icon: Icons.add_photo_alternate_rounded, style: ScrappButtonStyle.quiet, onPressed: () => _import(context)),
        ]),
        if (g.error != null) ...[
          const SizedBox(height: 10),
          Text(g.error!, style: const TextStyle(color: Palette.danger, fontWeight: FontWeight.w700)),
        ],
        if (g.feed.isNotEmpty) ...[
          const SectionTitle('Just now'),
          ...g.feed.map((f) => Padding(padding: const EdgeInsets.only(bottom: 10), child: _FeedCard(item: f))),
        ],
        SectionTitle('Recent captures', trailing: lib.loading ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2)) : null),
        if (lib.captures.isEmpty)
          const EmptyNote(icon: Icons.photo_camera_back_rounded, title: 'Nothing scrapbooked yet', body: 'Put on your glasses, look at something you love and say "scrapbook that".')
        else
          SizedBox(
            height: 132,
            child: ListView.separated(
              scrollDirection: Axis.horizontal,
              itemCount: lib.captures.length,
              separatorBuilder: (_, __) => const SizedBox(width: 10),
              itemBuilder: (context, i) {
                final c = lib.captures[i];
                return GestureDetector(
                  onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => CaptureScreen(captureId: c.id))),
                  child: Semantics(
                    label: 'Capture ${c.placeName ?? ''}',
                    button: true,
                    child: ClipRRect(
                      borderRadius: BorderRadius.circular(16),
                      child: Stack(children: [
                        Image.network(c.originalUrl ?? '', width: 100, height: 132, fit: BoxFit.cover,
                            errorBuilder: (_, __, ___) => Container(width: 100, color: Palette.card)),
                        if (c.processing)
                          const Positioned.fill(child: ColoredBox(color: Color(0x66000000), child: Center(child: CircularProgressIndicator(color: Palette.card)))),
                      ]),
                    ),
                  ),
                );
              },
            ),
          ),
      ]),
    );
  }

  Future<void> _import(BuildContext context) async {
    final g = context.read<GlassesState>();
    final source = await showModalBottomSheet<ImageSource>(
      context: context,
      backgroundColor: Palette.card,
      builder: (_) => SafeArea(
        child: Wrap(children: [
          ListTile(leading: const Icon(Icons.photo_camera_rounded), title: const Text('Phone camera'), onTap: () => Navigator.pop(context, ImageSource.camera)),
          ListTile(leading: const Icon(Icons.photo_library_rounded), title: const Text('From gallery'), onTap: () => Navigator.pop(context, ImageSource.gallery)),
        ]),
      ),
    );
    if (source == null) return;
    final x = await ImagePicker().pickImage(source: source, imageQuality: 92, maxWidth: 3000);
    if (x != null) await g.importPhoto(x.path);
  }
}

class _GlassesCard extends StatelessWidget {
  const _GlassesCard({required this.g});
  final GlassesState g;

  @override
  Widget build(BuildContext context) {
    final listening = g.speech == 'STARTED' || g.speech == 'LISTENING';
    return PaperCard(
      padding: const EdgeInsets.all(18),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          const Icon(Icons.visibility_rounded, size: 28),
          const SizedBox(width: 10),
          Expanded(child: Text(g.deviceName.isEmpty ? 'Meta glasses' : g.deviceName, style: ScrappType.display(26))),
        ]),
        const SizedBox(height: 10),
        Wrap(spacing: 8, runSpacing: 8, children: [
          Pill(label: g.registered ? 'Linked to Meta AI' : 'Not linked', icon: g.registered ? Icons.link_rounded : Icons.link_off_rounded, color: g.registered ? Palette.sage : Palette.paper),
          Pill(label: g.connected ? 'Connected' : 'Not connected', icon: Icons.bluetooth_rounded, color: g.connected ? Palette.sage : Palette.paper),
          if (g.armed) Pill(label: listening ? 'Listening' : 'Voice ${g.speech.toLowerCase()}', icon: Icons.mic_rounded, color: listening ? Palette.teal : Palette.paper),
          if (g.armed) Pill(label: 'Button ${g.inputs.toLowerCase()}', icon: Icons.radio_button_checked_rounded, color: g.inputs == 'ACTIVE' ? Palette.teal : Palette.paper),
        ]),
        const SizedBox(height: 14),
        if (!g.registered)
          ScrappButton(label: 'Link glasses in Meta AI', icon: Icons.link_rounded, expand: true, onPressed: () => GlassesBridge.register())
        else ...[
          ScrappButton(
            label: g.armed ? 'Stop scrapbooking' : 'Start scrapbooking',
            icon: g.armed ? Icons.stop_circle_rounded : Icons.play_circle_fill_rounded,
            style: g.armed ? ScrappButtonStyle.quiet : ScrappButtonStyle.primary,
            expand: true,
            onPressed: g.armed ? g.disarm : g.arm,
          ),
          const SizedBox(height: 10),
          Text(
            g.armed
                ? 'Say "scrapbook that" or press the capture button. Works with your phone in your pocket.'
                : 'Starting keeps a connection to your glasses open so voice and the capture button work hands-free.',
            style: const TextStyle(color: Palette.inkSoft),
          ),
        ],
        if (g.lastTranscript.isNotEmpty) ...[
          const SizedBox(height: 8),
          Text('Heard: "${g.lastTranscript}"', style: const TextStyle(fontStyle: FontStyle.italic, color: Palette.inkSoft)),
        ],
      ]),
    );
  }
}

class _FeedCard extends StatelessWidget {
  const _FeedCard({required this.item});
  final FeedItem item;

  @override
  Widget build(BuildContext context) {
    final (label, color, icon) = switch (item.state) {
      FeedState.uploading => ('Uploading original…', Palette.card, Icons.cloud_upload_rounded),
      FeedState.processing => ('Cutting stickers…', Palette.card, Icons.content_cut_rounded),
      FeedState.ready => (item.message ?? 'Done', Palette.sage, Icons.check_circle_rounded),
      FeedState.matched => (item.message ?? 'Found!', Palette.teal, Icons.emoji_events_rounded),
      FeedState.missed => (item.message ?? 'Saved', Palette.card, Icons.bookmark_added_rounded),
      FeedState.failed => (item.message ?? 'Failed', Palette.card, Icons.error_outline_rounded),
    };
    return PaperCard(
      color: color,
      padding: const EdgeInsets.all(10),
      onTap: item.captureId == null ? null : () => Navigator.push(context, MaterialPageRoute(builder: (_) => CaptureScreen(captureId: item.captureId!))),
      child: Row(children: [
        ClipRRect(borderRadius: BorderRadius.circular(12), child: Image.file(File(item.path), width: 56, height: 56, fit: BoxFit.cover, errorBuilder: (_, __, ___) => const SizedBox(width: 56, height: 56))),
        const SizedBox(width: 12),
        Icon(icon),
        const SizedBox(width: 8),
        Expanded(child: Text(label, style: const TextStyle(fontWeight: FontWeight.w800))),
        if (item.state == FeedState.uploading || item.state == FeedState.processing)
          const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2)),
      ]),
    );
  }
}
