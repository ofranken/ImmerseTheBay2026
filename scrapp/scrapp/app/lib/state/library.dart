import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/foundation.dart';

import '../models.dart';
import '../services/api.dart';

/// The user's own stuff: captures (originals), stickers, collages and 3D meshes.
class Library extends ChangeNotifier {
  Library(this._api);
  final ApiClient Function() _api;
  ApiClient get api => _api();

  List<Sticker> stickers = [];
  List<Sticker> received = [];
  List<Capture> captures = [];
  List<Collage> collages = [];
  List<MeshJob> meshes = [];
  bool loading = false;
  Timer? _meshPoll;

  Future<void> refreshAll() async {
    loading = true;
    notifyListeners();
    try {
      await Future.wait([refreshStickers(), refreshCaptures(), refreshCollages(), refreshMeshes()]);
    } finally {
      loading = false;
      notifyListeners();
    }
  }

  Future<void> refreshStickers() async {
    final mine = await api.get('/stickers', query: {'scope': 'mine'}) as List;
    final got = await api.get('/stickers', query: {'scope': 'received'}) as List;
    stickers = mine.map((e) => Sticker(Map<String, dynamic>.from(e))).toList();
    received = got.map((e) => Sticker(Map<String, dynamic>.from(e))).toList();
    notifyListeners();
  }

  Future<void> refreshCaptures() async {
    final r = await api.get('/captures') as List;
    captures = r.map((e) => Capture(Map<String, dynamic>.from(e))).toList();
    notifyListeners();
  }

  Future<Capture> capture(String id) async => Capture(Map<String, dynamic>.from(await api.get('/captures/$id')));

  Future<Sticker> cutAt(String captureId, double x, double y) async {
    final s = Sticker(Map<String, dynamic>.from(await api.post('/captures/$captureId/point', {'x': x, 'y': y})));
    stickers.insert(0, s);
    notifyListeners();
    return s;
  }

  Future<void> deleteSticker(String id) async {
    await api.delete('/stickers/$id');
    stickers.removeWhere((s) => s.id == id);
    notifyListeners();
  }

  Future<void> refreshCollages() async {
    final r = await api.get('/collages') as List;
    collages = r.map((e) => Collage(Map<String, dynamic>.from(e))).toList();
    notifyListeners();
  }

  Future<Collage> collage(String id) async => Collage(Map<String, dynamic>.from(await api.get('/collages/$id')));

  Future<Collage> saveCollage({String? id, required String title, required String sceneJson, required Uint8List png}) async {
    final r = await api.upload(id == null ? '/collages' : '/collages/$id',
        method: id == null ? 'POST' : 'PUT',
        fileField: 'thumbnail', bytes: png, filename: 'collage.png', mime: 'image/png',
        fields: {'title': title, 'scene': sceneJson});
    final c = Collage(Map<String, dynamic>.from(r));
    collages.removeWhere((x) => x.id == c.id);
    collages.insert(0, c);
    notifyListeners();
    return c;
  }

  Future<String> publishCollage(String id) async => (await api.post('/collages/$id/publish'))['url'] as String;

  Future<void> refreshMeshes() async {
    final r = await api.get('/meshes') as List;
    meshes = r.map((e) => MeshJob(Map<String, dynamic>.from(e))).toList();
    notifyListeners();
    _scheduleMeshPoll();
  }

  Future<MeshJob> meshFromText(String prompt) async => _addMesh(await api.post('/meshes/text', {'prompt': prompt}));
  Future<MeshJob> meshFromSticker(String stickerId) async => _addMesh(await api.post('/meshes/from-sticker', {'sticker_id': stickerId}));

  MeshJob _addMesh(dynamic r) {
    final m = MeshJob(Map<String, dynamic>.from(r));
    meshes.insert(0, m);
    notifyListeners();
    _scheduleMeshPoll();
    return m;
  }

  /// Meshy jobs take minutes; GET /meshes/{id} advances them server-side.
  void _scheduleMeshPoll() {
    _meshPoll?.cancel();
    if (!meshes.any((m) => !m.done && !m.failed)) return;
    _meshPoll = Timer(const Duration(seconds: 6), () async {
      for (var i = 0; i < meshes.length; i++) {
        final m = meshes[i];
        if (m.done || m.failed) continue;
        try {
          meshes[i] = MeshJob(Map<String, dynamic>.from(await api.get('/meshes/${m.id}')));
        } catch (_) {}
      }
      notifyListeners();
      _scheduleMeshPoll();
    });
  }

  @override
  void dispose() {
    _meshPoll?.cancel();
    super.dispose();
  }
}
