import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:webview_flutter/webview_flutter.dart';

import '../models.dart';
import '../services/asset_server.dart';
import '../state/app_state.dart';
import '../state/library.dart';
import '../theme/palette.dart';
import '../theme/theme.dart';
import '../widgets/fuzzy.dart';
import '../widgets/paper.dart';
import '../widgets/share_link_sheet.dart';
import '../widgets/share_dialog.dart';
import 'collage_editor_screen.dart';
import 'collage_view_screen.dart';

/// Collages (paper) and 3D generation (fuzz).
class StudioScreen extends StatefulWidget {
  const StudioScreen({super.key});
  @override
  State<StudioScreen> createState() => _StudioScreenState();
}

class _StudioScreenState extends State<StudioScreen> {
  int tab = 0;

  @override
  Widget build(BuildContext context) {
    final lib = context.watch<Library>();
    return ListView(padding: const EdgeInsets.fromLTRB(18, 12, 18, 32), children: [
      Text('STUDIO', style: ScrappType.display(34)),
      const SizedBox(height: 10),
      SegmentedButton<int>(
        segments: const [
          ButtonSegment(value: 0, label: Text('Collages'), icon: Icon(Icons.layers_rounded)),
          ButtonSegment(value: 1, label: Text('3D'), icon: Icon(Icons.grass_rounded)),
        ],
        selected: {tab},
        onSelectionChanged: (v) => setState(() => tab = v.first),
      ),
      const SizedBox(height: 14),
      if (tab == 0) ..._collages(context, lib) else ..._meshes(context, lib),
    ]);
  }

  List<Widget> _collages(BuildContext context, Library lib) => [
        ScrappButton(
          label: 'New collage',
          icon: Icons.add_rounded,
          expand: true,
          onPressed: () => Navigator.push(context, MaterialPageRoute(builder: (_) => const CollageEditorScreen())),
        ),
        const SizedBox(height: 14),
        if (lib.collages.isEmpty)
          const EmptyNote(icon: Icons.layers_outlined, title: 'No collages yet', body: 'Arrange stickers and 3D models in space, then save what is inside the box.'),
        GridView.count(
          shrinkWrap: true,
          physics: const NeverScrollableScrollPhysics(),
          crossAxisCount: 2,
          mainAxisSpacing: 12,
          crossAxisSpacing: 12,
          childAspectRatio: 0.82,
          children: [
            for (final c in lib.collages)
              PaperCard(
                padding: const EdgeInsets.all(8),
                onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => CollageEditorScreen(collage: c))),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Expanded(child: Stack(children: [
                    Positioned.fill(child: ClipRRect(
                      borderRadius: BorderRadius.circular(12),
                      child: c.thumbnailUrl == null ? Container(color: Palette.paper) : Image.network(c.thumbnailUrl!, fit: BoxFit.cover, width: double.infinity),
                    )),
                    Positioned(
                      right: 4,
                      top: 38,
                      child: Material(
                        color: Palette.card.withValues(alpha: 0.92),
                        shape: const StadiumBorder(),
                        child: InkWell(
                          customBorder: const StadiumBorder(),
                          onTap: () => showShareLinkSheet(context, collageId: c.id, title: c.title),
                          child: const Padding(
                            padding: EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                            child: Row(mainAxisSize: MainAxisSize.min, children: [
                              Icon(Icons.qr_code_2_rounded, size: 18, color: Palette.ink),
                              SizedBox(width: 4),
                              Text('Link', style: TextStyle(fontWeight: FontWeight.w900, fontSize: 13, color: Palette.ink)),
                            ]),
                          ),
                        ),
                      ),
                    ),
                    Positioned(
                      right: 4,
                      top: 4,
                      child: Material(
                        color: Palette.card.withValues(alpha: 0.92),
                        shape: const StadiumBorder(),
                        child: InkWell(
                          customBorder: const StadiumBorder(),
                          onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => CollageViewScreen(collage: c))),
                          child: const Padding(
                            padding: EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                            child: Row(mainAxisSize: MainAxisSize.min, children: [
                              Icon(Icons.threed_rotation_rounded, size: 18, color: Palette.ink),
                              SizedBox(width: 4),
                              Text('3D', style: TextStyle(fontWeight: FontWeight.w900, fontSize: 13, color: Palette.ink)),
                            ]),
                          ),
                        ),
                      ),
                    ),
                  ])),
                  const SizedBox(height: 6),
                  Text(c.title, maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontWeight: FontWeight.w800)),
                ]),
              ),
          ],
        ),
      ];

  List<Widget> _meshes(BuildContext context, Library lib) => [
        const _NewMeshCard(),
        const SizedBox(height: 16),
        for (final m in lib.meshes)
          Padding(
            padding: const EdgeInsets.only(bottom: 12),
            child: FuzzyPanel(
              onTap: m.done ? () => Navigator.push(context, MaterialPageRoute(builder: (_) => MeshPreviewScreen(mesh: m))) : null,
              child: Row(children: [
                ClipRRect(
                  borderRadius: BorderRadius.circular(14),
                  child: m.thumbnailUrl == null
                      ? Container(width: 64, height: 64, color: Palette.sageDeep, child: const Icon(Icons.grass_rounded))
                      : Image.network(m.thumbnailUrl!, width: 64, height: 64, fit: BoxFit.cover),
                ),
                const SizedBox(width: 14),
                Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(m.prompt ?? 'From a sticker', maxLines: 2, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 16)),
                  const SizedBox(height: 8),
                  if (m.failed)
                    Text('Failed: ${m.error ?? m.status}', style: const TextStyle(fontSize: 13))
                  else if (m.done)
                    const Text('Ready. Tap to preview.', style: TextStyle(fontSize: 13))
                  else ...[
                    FuzzyProgress(value: m.overall),
                    const SizedBox(height: 4),
                    Text(m.stage == 'refine' ? 'Painting textures…' : 'Sculpting…', style: const TextStyle(fontSize: 13)),
                  ],
                ])),
                IconButton(
                  tooltip: 'Delete',
                  icon: const Icon(Icons.delete_outline_rounded),
                  onPressed: () async {
                    try {
                      await context.read<Library>().deleteMesh(m.id);
                    } catch (e) {
                      if (context.mounted) toast(context, '$e');
                    }
                  },
                ),
              ]),
            ),
          ),
      ];
}

class _NewMeshCard extends StatefulWidget {
  const _NewMeshCard();
  @override
  State<_NewMeshCard> createState() => _NewMeshCardState();
}

class _NewMeshCardState extends State<_NewMeshCard> {
  final prompt = TextEditingController();
  bool busy = false;

  @override
  Widget build(BuildContext context) => FuzzyPanel(
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          const Text('GROW A 3D THING', style: TextStyle(fontSize: 22, letterSpacing: 0.5)),
          const SizedBox(height: 4),
          const Text('Describe it and Meshy sculpts a model for your collages.', style: TextStyle(fontWeight: FontWeight.w700)),
          const SizedBox(height: 12),
          TextField(
            controller: prompt,
            style: const TextStyle(color: Palette.ink, fontWeight: FontWeight.w700),
            decoration: const InputDecoration(hintText: 'a tiny ceramic frog wearing a beret', fillColor: Palette.card),
          ),
          const SizedBox(height: 12),
          ScrappButton(
            label: 'Grow it',
            icon: Icons.grass_rounded,
            style: ScrappButtonStyle.quiet,
            busy: busy,
            onPressed: () async {
              if (prompt.text.trim().length < 3) return;
              setState(() => busy = true);
              try {
                await context.read<Library>().meshFromText(prompt.text.trim());
                prompt.clear();
              } catch (e) {
                if (context.mounted) toast(context, '$e');
              } finally {
                if (mounted) setState(() => busy = false);
              }
            },
          ),
        ]),
      );
}

/// Turntable preview of a generated GLB on a fuzzy grass pedestal (editor.js mode=model).
class MeshPreviewScreen extends StatefulWidget {
  const MeshPreviewScreen({super.key, required this.mesh});
  final MeshJob mesh;
  @override
  State<MeshPreviewScreen> createState() => _MeshPreviewScreenState();
}

class _MeshPreviewScreenState extends State<MeshPreviewScreen> {
  final web = WebViewController()
    ..setJavaScriptMode(JavaScriptMode.unrestricted)
    ..setBackgroundColor(Palette.paper);

  /// A model a friend sent you can be previewed but not re-sent (the server only lets owners share).
  bool get mine => widget.mesh.j['owner_id'] == null || widget.mesh.j['owner_id'] == context.read<AppState>().user?.id;

  @override
  void initState() {
    super.initState();
    LocalAssetServer.start().then((base) => web.loadRequest(Uri.parse('$base/editor.html?mode=model&src=${Uri.encodeComponent(widget.mesh.glbUrl!)}')));
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(
          title: Text((widget.mesh.prompt ?? '3D MODEL').toUpperCase(), overflow: TextOverflow.ellipsis),
          actions: [
            if (mine && widget.mesh.done)
              IconButton(
                tooltip: 'Send to friends',
                icon: const Icon(Icons.send_rounded),
                onPressed: () => shareWithFriends(context, kind: 'mesh', itemId: widget.mesh.id, title: 'Send 3D model to'),
              ),
          ],
        ),
        body: PaperBackground(child: WebViewWidget(controller: web)),
      );
}
