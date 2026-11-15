import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:path_provider/path_provider.dart';
import 'package:provider/provider.dart';
import 'package:share_plus/share_plus.dart';
import 'package:webview_flutter/webview_flutter.dart';

import '../collage_background.dart';
import '../models.dart';
import '../services/asset_server.dart';
import '../state/library.dart';
import '../state/social.dart';
import '../theme/palette.dart';
import '../theme/theme.dart';
import '../widgets/fuzzy.dart';
import '../widgets/paper.dart';
import '../widgets/saved_burst.dart';
import '../widgets/share_link_sheet.dart';
import 'collage_view_screen.dart';

/// 3D collage workspace. Rendering and touch manipulation happen in three.js (assets/web/editor.js);
/// this screen is the paper toolbar around it and the bridge to the backend.
class CollageEditorScreen extends StatefulWidget {
  const CollageEditorScreen({super.key, this.collage, this.seedStickers = const []});
  final Collage? collage;
  final List<Sticker> seedStickers;
  @override
  State<CollageEditorScreen> createState() => _CollageEditorScreenState();
}

class _CollageEditorScreenState extends State<CollageEditorScreen> {
  late final WebViewController web;
  bool ready = false;
  String? collageId;
  String title = 'Untitled collage';
  String mode = 'move';
  String? selectedKind;
  int inside = 0, outside = 0;
  bool zoneVisible = true;
  String preset = 'square';
  double pixelate = 0, motionBlur = 0;
  int resolution = 2048;
  bool paperBackground = true, stereo = false, saving = false;
  Map<String, dynamic>? background; // scene.background as last reported by the editor (null = default paper)
  final _chunks = <String, List<String?>>{};
  final _glbChunks = <String, List<String?>>{}; // the AR model rides along with the picture

  @override
  void initState() {
    super.initState();
    collageId = widget.collage?.id;
    title = widget.collage?.title ?? title;
    web = WebViewController()
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..setBackgroundColor(Palette.paper)
      ..addJavaScriptChannel('Scrapp', onMessageReceived: (m) => _onMessage(m.message));
    LocalAssetServer.start().then((base) => web.loadRequest(Uri.parse('$base/editor.html?mode=edit')));
  }

  Future<void> _cmd(Map<String, dynamic> c) => web.runJavaScript('window.ScrappEditor.command(${jsonEncode(c)})');

  Future<void> _onMessage(String raw) async {
    final m = jsonDecode(raw) as Map<String, dynamic>;
    switch (m['type']) {
      case 'ready':
        setState(() => ready = true);
        if (collageId != null) {
          final fresh = await context.read<Library>().collage(collageId!); // re-signed media URLs
          await _cmd({'cmd': 'load', 'scene': fresh.scene});
        }
        for (final s in widget.seedStickers) {
          await _addSticker(s);
        }
      case 'selection':
        setState(() => selectedKind = m['kind'] as String?);
      case 'background':
        setState(() => background = m['background'] == null ? null : Map<String, dynamic>.from(m['background']));
      case 'zoneStats':
        setState(() {
          inside = (m['inside'] as num).toInt();
          outside = (m['outside'] as num).toInt();
        });
      case 'export_chunk':
        final list = _chunks.putIfAbsent(m['id'], () => List<String?>.filled((m['total'] as num).toInt(), null));
        list[(m['index'] as num).toInt()] = m['data'] as String;
      case 'glb_chunk':
        final list = _glbChunks.putIfAbsent(m['id'], () => List<String?>.filled((m['total'] as num).toInt(), null));
        list[(m['index'] as num).toInt()] = m['data'] as String;
      case 'glb_failed':
        // not fatal: the collage saves anyway, it just gets no "View in AR" button on its link
        debugPrint('AR model export failed: ${m['message']}');
      case 'export_done':
        await _finishSave(m['id'] as String, Map<String, dynamic>.from(m['scene']));
      case 'error':
        if (mounted) toast(context, m['message'].toString());
    }
  }

  Future<void> _addSticker(Sticker s) => _cmd({'cmd': 'addSticker', 'url': s.imageUrl, 'ref_id': s.id, 'title': s.title});

  Future<void> _save() async {
    setState(() => saving = true);
    await _cmd({'cmd': 'export', 'resolution': resolution, 'background': paperBackground ? 'paper' : 'transparent', 'stereo': stereo});
  }

  Future<void> _finishSave(String exportId, Map<String, dynamic> scene) async {
    final parts = _chunks.remove(exportId);
    if (parts == null || parts.contains(null)) {
      setState(() => saving = false);
      return;
    }
    final png = base64Decode(parts.join());
    final glbParts = _glbChunks.remove(exportId);
    final glb = (glbParts == null || glbParts.contains(null)) ? null : base64Decode(glbParts.join());
    try {
      final c = await context.read<Library>().saveCollage(id: collageId, title: title, sceneJson: jsonEncode(scene), png: png, glb: glb);
      collageId = c.id;
      if (mounted) await showSavedBurst(context, png);
      if (mounted) _afterSave(png);
    } catch (e) {
      if (mounted) toast(context, 'Save failed: $e');
    } finally {
      if (mounted) setState(() => saving = false);
    }
  }

  void _afterSave(Uint8List png) {
    showModalBottomSheet(
      context: context,
      backgroundColor: Palette.card,
      builder: (ctx) => SafeArea(
        child: Wrap(children: [
          ListTile(
            leading: const Icon(Icons.ios_share_rounded),
            title: const Text('Share image (Instagram, Pinterest, Tumblr…)'),
            onTap: () async {
              Navigator.pop(ctx);
              final f = File('${(await getTemporaryDirectory()).path}/scrapp_collage.png');
              await f.writeAsBytes(png);
              await Share.shareXFiles([XFile(f.path)], text: 'Made with Scrapp');
            },
          ),
          ListTile(
            leading: const Icon(Icons.public_rounded),
            title: const Text('Share a 3D link (QR code)'),
            onTap: () {
              Navigator.pop(ctx);
              showShareLinkSheet(context, collageId: collageId!, title: title);
            },
          ),
          ListTile(
            leading: const Icon(Icons.send_rounded),
            title: const Text('Send to friends in Scrapp'),
            onTap: () {
              Navigator.pop(ctx);
              _sendToFriends();
            },
          ),
        ]),
      ),
    );
  }

  /// The saved version (what "View in 3D" shows is what was last saved, not unsaved edits).
  void _viewIn3d() {
    final lib = context.read<Library>();
    final c = lib.collages.where((x) => x.id == collageId).firstOrNull ?? widget.collage;
    if (c == null) return;
    Navigator.push(context, MaterialPageRoute(builder: (_) => CollageViewScreen(collage: c)));
  }

  Future<void> _sendToFriends() async {
    final social = context.read<Social>();
    await social.refreshFriends();
    if (!mounted) return;
    final picked = <String>{};
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => StatefulBuilder(builder: (ctx, set) => AlertDialog(
        backgroundColor: Palette.card,
        title: const Text('Send collage to'),
        content: Wrap(spacing: 8, children: [
          for (final f in social.friends)
            FilterChip(label: Text(f.displayName), selected: picked.contains(f.id), onSelected: (v) => set(() => v ? picked.add(f.id) : picked.remove(f.id))),
        ]),
        actions: [TextButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Send'))],
      )),
    );
    if (ok == true && picked.isNotEmpty) {
      await social.share(kind: 'collage', itemId: collageId!, to: picked.toList());
      if (mounted) toast(context, 'Collage sent');
    }
  }

  Future<void> _pickSticker() async {
    final lib = context.read<Library>();
    final all = [...lib.stickers, ...lib.received];
    final s = await showModalBottomSheet<Sticker>(
      context: context,
      backgroundColor: Palette.card,
      builder: (ctx) => SizedBox(
        height: 380,
        child: GridView.count(
          padding: const EdgeInsets.all(16),
          crossAxisCount: 4,
          mainAxisSpacing: 10,
          crossAxisSpacing: 10,
          children: [for (final s in all) GestureDetector(onTap: () => Navigator.pop(ctx, s), child: StickerImage(url: s.imageUrl, size: 76))],
        ),
      ),
    );
    if (s != null) await _addSticker(s);
  }

  Future<void> _pickMesh() async {
    final meshes = context.read<Library>().meshes.where((m) => m.done).toList();
    final m = await showModalBottomSheet<MeshJob>(
      context: context,
      backgroundColor: Palette.card,
      builder: (ctx) => Padding(
        padding: const EdgeInsets.all(16),
        child: meshes.isEmpty
            ? const Text('No finished 3D models yet. Grow one in Studio → 3D.')
            : Wrap(spacing: 10, runSpacing: 10, children: [
                for (final m in meshes)
                  FuzzyPanel(
                    padding: const EdgeInsets.all(8),
                    radius: 18,
                    onTap: () => Navigator.pop(ctx, m),
                    child: SizedBox(width: 90, child: Column(children: [
                      if (m.thumbnailUrl != null) ClipRRect(borderRadius: BorderRadius.circular(10), child: Image.network(m.thumbnailUrl!, height: 70, fit: BoxFit.cover)),
                      Text(m.prompt ?? '3D', maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 12)),
                    ])),
                  ),
              ]),
      ),
    );
    if (m != null) await _cmd({'cmd': 'addMesh', 'url': m.glbUrl, 'ref_id': m.id, 'title': m.prompt});
  }

  Future<void> _setBackground(Map<String, dynamic>? bg) async {
    if (!isValidBackground(bg)) return;
    await _cmd({'cmd': 'setBackground', 'background': bg});
  }

  void _backgroundSheet() {
    final captures = context.read<Library>().captures.where((c) => c.originalUrl != null).take(24).toList();
    showModalBottomSheet(
      context: context,
      backgroundColor: Palette.card,
      isScrollControlled: true,
      builder: (ctx) => SafeArea(
        child: ConstrainedBox(
          constraints: BoxConstraints(maxHeight: MediaQuery.of(ctx).size.height * 0.7),
          child: ListView(padding: const EdgeInsets.all(20), shrinkWrap: true, children: [
            Text('BACKGROUND', style: ScrappType.display(26)),
            const SizedBox(height: 4),
            const Text('Shows behind your collage, in the saved picture and on the web link.', style: TextStyle(color: Palette.inkSoft)),
            const SizedBox(height: 14),
            Wrap(spacing: 12, runSpacing: 12, children: [
              for (final p in backgroundPresets)
                _BackgroundSwatch(
                  label: p.label,
                  selected: sameBackground(background, p.json),
                  color: p.swatch,
                  gradient: p.gradient,
                  onTap: () {
                    _setBackground(p.json);
                    Navigator.pop(ctx);
                  },
                ),
            ]),
            const SectionTitle('One of your photos'),
            if (captures.isEmpty)
              const Text('Photos you scrapbook show up here.', style: TextStyle(color: Palette.inkSoft))
            else
              SizedBox(
                height: 84,
                child: ListView.separated(
                  scrollDirection: Axis.horizontal,
                  itemCount: captures.length,
                  separatorBuilder: (_, __) => const SizedBox(width: 10),
                  itemBuilder: (_, i) {
                    final c = captures[i];
                    final on = background?['type'] == 'photo' && background?['ref_id'] == c.id;
                    return GestureDetector(
                      onTap: () {
                        _setBackground(photoBackground(c.id, c.originalUrl));
                        Navigator.pop(ctx);
                      },
                      child: Container(
                        decoration: BoxDecoration(borderRadius: BorderRadius.circular(14), border: Border.all(color: on ? Palette.tealDeep : Colors.transparent, width: 3)),
                        child: ClipRRect(borderRadius: BorderRadius.circular(11), child: Image.network(c.originalUrl!, width: 84, height: 78, fit: BoxFit.cover, errorBuilder: (_, __, ___) => Container(width: 84, color: Palette.paper))),
                      ),
                    );
                  },
                ),
              ),
          ]),
        ),
      ),
    );
  }

  void _filtersSheet() {
    showModalBottomSheet(
      context: context,
      backgroundColor: Palette.card,
      builder: (ctx) => StatefulBuilder(builder: (ctx, set) {
        void update(VoidCallback f) {
          set(f);
          setState(() {});
          _cmd({'cmd': 'filters', 'pixelate': pixelate.round(), 'motionBlur': motionBlur});
        }

        return Padding(
          padding: const EdgeInsets.all(20),
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('FILTERS & EXPORT', style: ScrappType.display(26)),
            Text('Pixelate ${pixelate.round() == 0 ? 'off' : pixelate.round()}', style: const TextStyle(fontWeight: FontWeight.w800)),
            Slider(value: pixelate, min: 0, max: 12, divisions: 12, onChanged: (v) => update(() => pixelate = v)),
            Text('Motion blur ${(motionBlur * 100).round()}%', style: const TextStyle(fontWeight: FontWeight.w800)),
            Slider(value: motionBlur, onChanged: (v) => update(() => motionBlur = v)),
            const Text('Save resolution', style: TextStyle(fontWeight: FontWeight.w800)),
            Wrap(spacing: 8, children: [
              for (final r in [1080, 2048, 4096]) ChoiceChip(label: Text('${r}px'), selected: resolution == r, onSelected: (_) => update(() => resolution = r)),
            ]),
            SwitchListTile(contentPadding: EdgeInsets.zero, title: const Text('Paper background'), value: paperBackground, onChanged: (v) => update(() => paperBackground = v)),
            SwitchListTile(contentPadding: EdgeInsets.zero, title: const Text('Stereo pair (3D viewers)'), value: stereo, onChanged: (v) => update(() => stereo = v)),
          ]),
        );
      }),
    );
  }

  Future<void> _rename() async {
    final c = TextEditingController(text: title);
    final t = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: Palette.card,
        title: const Text('Collage name'),
        content: TextField(controller: c, autofocus: true),
        actions: [TextButton(onPressed: () => Navigator.pop(ctx, c.text), child: const Text('OK'))],
      ),
    );
    if (t != null && t.trim().isNotEmpty) setState(() => title = t.trim());
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: GestureDetector(onTap: _rename, child: Text(title.toUpperCase(), overflow: TextOverflow.ellipsis)),
        actions: [
          if (collageId != null)
            IconButton(tooltip: 'View in 3D', icon: const Icon(Icons.threed_rotation_rounded), onPressed: _viewIn3d),
          if (collageId != null)
            IconButton(tooltip: 'Share 3D link', icon: const Icon(Icons.qr_code_2_rounded), onPressed: () => showShareLinkSheet(context, collageId: collageId!, title: title)),
          IconButton(tooltip: 'Background', icon: const Icon(Icons.wallpaper_rounded), onPressed: _backgroundSheet),
          IconButton(tooltip: 'Filters & export settings', icon: const Icon(Icons.auto_fix_high_rounded), onPressed: _filtersSheet),
          PopupMenuButton<String>(
            tooltip: 'Clear',
            icon: const Icon(Icons.cleaning_services_rounded),
            color: Palette.card,
            onSelected: (w) => _cmd({'cmd': 'clear', 'which': w}),
            itemBuilder: (_) => const [
              PopupMenuItem(value: 'outside', child: Text('Clear outside the box')),
              PopupMenuItem(value: 'inside', child: Text('Clear inside the box')),
              PopupMenuItem(value: 'all', child: Text('Clear everything')),
            ],
          ),
        ],
      ),
      body: PaperBackground(
        child: Column(children: [
          Expanded(child: Stack(children: [
            WebViewWidget(controller: web),
            if (!ready) const Center(child: CircularProgressIndicator()),
            Positioned(
              left: 12,
              top: 8,
              child: Wrap(spacing: 6, children: [
                Pill(label: '$inside in box', icon: Icons.check_box_rounded, color: Palette.sage),
                Pill(label: '$outside left out', icon: Icons.indeterminate_check_box_rounded, color: Palette.card, fg: Palette.outside),
              ]),
            ),
          ])),
          _toolbar(),
        ]),
      ),
    );
  }

  Widget _toolbar() {
    return Container(
      padding: const EdgeInsets.fromLTRB(12, 10, 12, 14),
      decoration: BoxDecoration(
        color: Palette.card,
        borderRadius: const BorderRadius.vertical(top: Radius.circular(26)),
        boxShadow: [BoxShadow(color: Palette.inkSoft.withValues(alpha: 0.2), blurRadius: 14, offset: const Offset(0, -4))],
      ),
      child: SafeArea(
        top: false,
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: Row(children: [
              ScrappButton(label: 'Sticker', icon: Icons.add_rounded, onPressed: ready ? _pickSticker : null),
              const SizedBox(width: 8),
              FuzzyButton(label: '3D', icon: Icons.grass_rounded, onPressed: ready ? _pickMesh : null),
              const SizedBox(width: 8),
              for (final (m, icon) in [('move', Icons.open_with_rounded), ('rotate', Icons.threesixty_rounded), ('scale', Icons.zoom_out_map_rounded), ('depth', Icons.height_rounded)])
                Padding(
                  padding: const EdgeInsets.only(right: 6),
                  child: ChoiceChip(
                    avatar: Icon(icon, size: 18),
                    label: Text(m),
                    selected: mode == m,
                    onSelected: (_) {
                      setState(() => mode = m);
                      _cmd({'cmd': 'setMode', 'mode': m});
                    },
                  ),
                ),
              IconButton(tooltip: 'Duplicate', onPressed: selectedKind == null ? null : () => _cmd({'cmd': 'duplicateSelected'}), icon: const Icon(Icons.copy_rounded)),
              IconButton(tooltip: 'Delete', onPressed: selectedKind == null ? null : () => _cmd({'cmd': 'deleteSelected'}), icon: const Icon(Icons.delete_outline_rounded)),
            ]),
          ),
          const SizedBox(height: 8),
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: Row(children: [
              FilterChip(
                label: const Text('Save box'),
                selected: zoneVisible,
                onSelected: (v) {
                  setState(() => zoneVisible = v);
                  _cmd({'cmd': 'zone', 'visible': v});
                },
              ),
              const SizedBox(width: 6),
              for (final p in ['square', 'portrait', 'landscape', 'tower', 'panorama'])
                Padding(
                  padding: const EdgeInsets.only(right: 6),
                  child: ChoiceChip(
                    label: Text(p),
                    selected: preset == p,
                    onSelected: (_) {
                      setState(() => preset = p);
                      _cmd({'cmd': 'zone', 'preset': p, 'visible': true});
                    },
                  ),
                ),
              TextButton(onPressed: selectedKind == null ? null : () => _cmd({'cmd': 'zoneToSelection'}), child: const Text('Center on selection')),
            ]),
          ),
          const SizedBox(height: 10),
          ScrappButton(label: saving ? 'Saving…' : 'Save to collection', icon: Icons.bookmark_add_rounded, expand: true, busy: saving, onPressed: ready && inside > 0 ? _save : null),
        ]),
      ),
    );
  }
}

class _BackgroundSwatch extends StatelessWidget {
  const _BackgroundSwatch({required this.label, required this.selected, required this.onTap, this.color, this.gradient});
  final String label;
  final bool selected;
  final VoidCallback onTap;
  final Color? color;
  final List<Color>? gradient;

  @override
  Widget build(BuildContext context) => GestureDetector(
        onTap: onTap,
        child: SizedBox(
          width: 68,
          child: Column(children: [
            Container(
              width: 56,
              height: 56,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: gradient == null ? color : null,
                gradient: gradient == null ? null : LinearGradient(begin: Alignment.topCenter, end: Alignment.bottomCenter, colors: gradient!),
                border: Border.all(color: selected ? Palette.tealDeep : Palette.ink.withValues(alpha: 0.25), width: selected ? 4 : 1.5),
              ),
              child: selected ? const Icon(Icons.check_rounded, size: 22) : null,
            ),
            const SizedBox(height: 4),
            Text(label, maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w700)),
          ]),
        ),
      );
}
