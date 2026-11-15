import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:webview_flutter/webview_flutter.dart';

import '../models.dart';
import '../services/asset_server.dart';
import '../services/collage_ar.dart';
import '../state/library.dart';
import '../theme/palette.dart';
import '../widgets/paper.dart';
import '../widgets/share_link_sheet.dart';

/// A finished collage in 3D: a slow camera drift, tilt-the-phone parallax, or free orbit (assets/web/viewer_fx.js, mode=view).
/// The scene is pushed in from here (fresh signed media URLs), so it works for collages that are not published.
class CollageViewScreen extends StatefulWidget {
  const CollageViewScreen({super.key, required this.collage});
  final Collage collage;
  @override
  State<CollageViewScreen> createState() => _CollageViewScreenState();
}

class _CollageViewScreenState extends State<CollageViewScreen> {
  late final WebViewController web;
  bool ready = false;
  String? error;

  @override
  void initState() {
    super.initState();
    web = WebViewController()
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..setBackgroundColor(Palette.paper)
      ..addJavaScriptChannel('Scrapp', onMessageReceived: (m) => _onMessage(m.message));
    LocalAssetServer.start().then((base) => web.loadRequest(Uri.parse('$base/editor.html?mode=view')));
  }

  Future<void> _onMessage(String raw) async {
    final m = jsonDecode(raw) as Map<String, dynamic>;
    switch (m['type']) {
      case 'ready':
        try {
          final fresh = await context.read<Library>().collage(widget.collage.id);
          await web.runJavaScript('window.ScrappEditor.command(${jsonEncode({'cmd': 'load', 'scene': fresh.scene, 'title': fresh.title})})');
        } catch (e) {
          if (mounted) setState(() => error = '$e');
        }
      case 'viewer_ready':
        if (mounted) setState(() => ready = true);
      case 'error':
        if (mounted && m['message'] != null) toast(context, m['message'].toString());
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(
          title: Text(widget.collage.title.toUpperCase(), overflow: TextOverflow.ellipsis),
          actions: [
            IconButton(
              tooltip: 'View in AR',
              icon: const Icon(Icons.view_in_ar_rounded),
              onPressed: () => viewSavedCollageInAr(context, collageId: widget.collage.id, title: widget.collage.title),
            ),
            IconButton(
              tooltip: 'Share 3D link',
              icon: const Icon(Icons.qr_code_2_rounded),
              onPressed: () => showShareLinkSheet(context, collageId: widget.collage.id, title: widget.collage.title),
            ),
          ],
        ),
        body: PaperBackground(
          child: Stack(children: [
            WebViewWidget(controller: web),
            if (!ready && error == null) const Center(child: CircularProgressIndicator()),
            if (error != null) Center(child: Padding(padding: const EdgeInsets.all(24), child: Text('Could not open this collage: $error', textAlign: TextAlign.center))),
          ]),
        ),
      );
}
