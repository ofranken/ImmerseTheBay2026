import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models.dart';
import '../state/library.dart';
import '../widgets/paper.dart';
import 'ar_bridge.dart';

/// Turns an editor scene (assets/web/editor.js `sceneJson()`) into the items the native collage AR screen draws
/// (android/.../ar/CollageArActivity.kt). Saved scenes carry no URLs, so each item's media URL is looked up by item id
/// first (a freshly fetched collage, whose URLs the server has just signed), then by ref_id (the user's own stickers and
/// models). Items with no URL (deleted sticker, unfinished model) are left out rather than failing the whole collage.
List<Map<String, dynamic>> collageArItems(
  Map<String, dynamic> scene, {
  Map<String, String> urlByItemId = const {},
  Map<String, String> urlByRefId = const {},
}) {
  final out = <Map<String, dynamic>>[];
  for (final raw in _list(scene['items'])) {
    if (raw is! Map) continue;
    final it = Map<String, dynamic>.from(raw);
    final kind = it['kind'] == 'mesh' ? 'mesh' : 'sticker';
    final id = (it['id'] ?? '').toString();
    final ref = it['ref_id']?.toString();
    final url = _nonEmpty(it['url']) ?? urlByItemId[id] ?? (ref == null ? null : urlByRefId[ref]);
    if (url == null) continue;
    out.add({
      'id': id.isEmpty ? 'item${out.length}' : id,
      'kind': kind,
      'url': url,
      'title': it['title'],
      'position': _nums(it['position'], 3, 0),
      'quaternion': _nums(it['quaternion'], 4, 0, last: 1),
      'scale': it['scale'] is num ? (it['scale'] as num).toDouble() : 1.0,
    });
  }
  return out;
}

/// item id -> URL from a scene that already has URLs (e.g. GET /collages/{id}).
Map<String, String> sceneUrls(Map<String, dynamic> scene) => {
      for (final raw in _list(scene['items']))
        if (raw is Map && raw['id'] != null && _nonEmpty(raw['url']) != null) raw['id'].toString(): raw['url'] as String,
    };

/// ref_id -> URL for everything in the user's own library (covers items added since the last save).
Map<String, String> libraryUrls(List<Sticker> stickers, List<MeshJob> meshes) => {
      for (final s in stickers)
        if (s.imageUrl != null) s.id: s.imageUrl!,
      for (final m in meshes)
        if (m.glbUrl != null) m.id: m.glbUrl!,
    };

List<dynamic> _list(Object? v) => v is List ? v : const [];

String? _nonEmpty(Object? v) => v is String && v.isNotEmpty ? v : null;

List<double> _nums(Object? v, int n, double fill, {double? last}) {
  final l = v is List ? v : const [];
  final out = List<double>.generate(n, (i) => i < l.length && l[i] is num ? (l[i] as num).toDouble() : fill);
  if (last != null && l.length < n) out[n - 1] = last; // a missing quaternion is the identity, not all zeros
  return out;
}

/// Opens the native AR screen for a whole collage. Returns false when nothing could be shown.
Future<bool> openCollageAr({required String title, required List<Map<String, dynamic>> items}) async {
  if (items.isEmpty) return false;
  await ArBridge.openCollage(title: title, items: items);
  return true;
}

/// View in AR for a saved collage (the 3D view screen): fresh signed URLs from the server, the library as a fallback.
Future<void> viewSavedCollageInAr(BuildContext context, {required String collageId, required String title}) async {
  try {
    if (!await ArBridge.available()) {
      if (context.mounted) toast(context, 'AR is not supported on this phone');
      return;
    }
    if (!context.mounted) return;
    final lib = context.read<Library>();
    final scene = (await lib.collage(collageId)).scene;
    final items = collageArItems(scene, urlByRefId: libraryUrls(lib.stickers, lib.meshes));
    if (!await openCollageAr(title: title, items: items) && context.mounted) toast(context, 'Nothing in this collage can be shown in AR yet');
  } catch (e) {
    if (context.mounted) toast(context, 'Could not open AR: $e');
  }
}
