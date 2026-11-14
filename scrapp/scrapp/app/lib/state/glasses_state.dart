import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';

import '../models.dart';
import '../services/glasses_bridge.dart';
import '../services/location.dart';
import 'app_state.dart';
import 'library.dart';
import 'social.dart';

enum FeedState { uploading, processing, ready, matched, missed, failed }

/// One capture moving through the pipeline, shown on the Scrap tab.
class FeedItem {
  FeedItem({required this.localId, required this.path, this.state = FeedState.uploading});
  final String localId;
  final String path;
  FeedState state;
  String? captureId;
  String? message;
  int stickers = 0;
}

/// Glasses connection + the capture pipeline:
/// trigger ("scrapbook that" / capture button / app) -> native photo + GPS saved to the outbox
/// -> upload original -> SAM stickers on the server (or hunt check-off) -> spoken result.
class GlassesState extends ChangeNotifier {
  GlassesState(this.app, this.library, this.social);
  final AppState app;
  final Library library;
  final Social social;

  Map<String, dynamic> status = {};
  String lastTranscript = '';
  bool armed = false;
  bool initialized = false;
  String? error;
  Hunt? activeHunt;
  final feed = <FeedItem>[];
  StreamSubscription? _sub;
  final _uploading = <String>{};

  String get registration => status['registration']?.toString() ?? 'unknown';
  bool get registered => registration == 'REGISTERED';
  String get deviceName => status['deviceName']?.toString() ?? '';
  String get session => status['session']?.toString() ?? 'NONE';
  String get speech => status['speech']?.toString() ?? 'OFF';
  String get inputs => status['inputs']?.toString() ?? 'OFF';
  bool get connected => status['connected'] == true;

  Future<void> start() async {
    _sub ??= GlassesBridge.events.listen(_onEvent, onError: (e) => error = '$e');
    try {
      if (app.glasses.mockDevice) await GlassesBridge.setMockDevice(true);
      status = await GlassesBridge.initialize();
      initialized = true;
      armed = status['armed'] == true;
      if (await GlassesBridge.consumeVoiceLaunch()) await arm(); // "Hey Meta, start Scrapp"
    } catch (e) {
      error = 'Glasses bridge unavailable: $e';
    }
    notifyListeners();
    await drainOutbox();
  }

  void _onEvent(Map<String, dynamic> e) {
    switch (e['type']) {
      case 'status':
        status = {...status, ...e};
        armed = status['armed'] == true;
      case 'transcript':
        lastTranscript = e['text']?.toString() ?? '';
      case 'captured':
        _upload(PendingCapture(id: e['id'], path: e['path'], meta: Map<String, dynamic>.from(jsonDecode(e['meta'] ?? '{}'))));
      case 'captureFailed':
        error = 'Capture failed: ${e['reason']}';
      case 'voiceInvocation':
        arm();
    }
    notifyListeners();
  }

  Future<void> refreshStatus() async {
    try {
      status = await GlassesBridge.status();
      armed = status['armed'] == true;
      notifyListeners();
    } catch (_) {}
  }

  Future<void> arm() async {
    error = null;
    await LocationService.ensurePermission(); // location tags are captured natively at shutter time
    await GlassesBridge.arm(warmCamera: app.glasses.warmCamera, voice: app.glasses.voice, button: app.glasses.button);
    await refreshStatus();
  }

  Future<void> disarm() async {
    await GlassesBridge.disarm();
    await refreshStatus();
  }

  Future<void> setActiveHunt(Hunt? h) async {
    activeHunt = h;
    await GlassesBridge.setActiveHunt(h?.id, h?.title);
    notifyListeners();
  }

  /// Uploads anything the native side captured while the app was not listening.
  Future<void> drainOutbox() async {
    try {
      for (final p in await GlassesBridge.pendingCaptures()) {
        await _upload(p);
      }
    } catch (_) {}
  }

  /// Phone-only path (no glasses): pick or shoot a photo and run the same pipeline.
  Future<void> importPhoto(String path) async {
    final pos = await LocationService.current();
    final meta = <String, dynamic>{
      'captured_at': DateTime.now().toUtc().toIso8601String(),
      'trigger': 'import',
      if (pos != null) ...{'lat': pos.latitude, 'lng': pos.longitude, 'accuracy_m': pos.accuracy, 'altitude_m': pos.altitude},
      if (activeHunt != null) 'hunt_id': activeHunt!.id,
    };
    await _upload(PendingCapture(id: 'import-${DateTime.now().millisecondsSinceEpoch}', path: path, meta: meta), native: false);
  }

  Future<void> _upload(PendingCapture p, {bool native = true}) async {
    if (!_uploading.add(p.id)) return;
    final item = FeedItem(localId: p.id, path: p.path);
    feed.insert(0, item);
    if (feed.length > 12) feed.removeLast();
    notifyListeners();
    try {
      final meta = Map<String, dynamic>.from(p.meta);
      final lat = (meta['lat'] as num?)?.toDouble(), lng = (meta['lng'] as num?)?.toDouble();
      if (lat != null && lng != null && meta['place_name'] == null) meta['place_name'] = await LocationService.placeName(lat, lng);
      final huntId = meta.remove('hunt_id') as String?;
      final fields = {'meta': jsonEncode(meta)};

      if (huntId != null) {
        final r = Map<String, dynamic>.from(await app.api.upload('/hunts/$huntId/attempt', fileField: 'image', filePath: p.path, fields: fields));
        final hunt = social.replaceFromJson(Map<String, dynamic>.from(r['hunt']));
        if (activeHunt?.id == hunt.id) activeHunt = hunt;
        item.captureId = (r['capture'] as Map)['id'];
        if (r['matched'] == true) {
          final title = (r['item'] as Map)['title'];
          item.state = FeedState.matched;
          item.message = 'Found "$title"  ${hunt.foundCount}/${hunt.total}';
          await GlassesBridge.speak(hunt.foundCount == hunt.total
              ? 'You found all ${hunt.total}! Hunt complete.'
              : 'Found $title. ${hunt.foundCount} of ${hunt.total}.');
        } else {
          item.state = FeedState.missed;
          item.message = 'Not on the list. Saved to your scrapbook.';
          await GlassesBridge.speak('Not on the list yet. Saved to your scrapbook.');
        }
      } else {
        final r = Map<String, dynamic>.from(await app.api.upload('/captures', fileField: 'image', filePath: p.path, fields: fields));
        item.captureId = r['id'];
        item.state = FeedState.processing;
        notifyListeners();
        final done = await _waitForStickers(item.captureId!);
        item.stickers = done.stickers.length;
        item.state = done.status == 'failed' ? FeedState.failed : FeedState.ready;
        item.message = item.stickers == 0 ? 'No objects found. Tap to cut one by hand.' : '${item.stickers} new stickers';
        if (native) await GlassesBridge.speak(item.stickers == 0 ? 'Saved. No stickers this time.' : 'Scrapbooked. ${item.stickers} stickers.');
      }
      if (native) await GlassesBridge.ackCapture(p.id); // original is now safe on the server
      unawaited(library.refreshStickers());
      unawaited(library.refreshCaptures());
    } catch (e) {
      item.state = FeedState.failed;
      item.message = 'Upload failed, will retry: $e';
    } finally {
      _uploading.remove(p.id);
      notifyListeners();
    }
  }

  Future<Capture> _waitForStickers(String id) async {
    for (var i = 0; i < 45; i++) {
      final c = await library.capture(id);
      if (!c.processing) return c;
      await Future<void>.delayed(const Duration(seconds: 2));
    }
    return library.capture(id);
  }

  @override
  void dispose() {
    _sub?.cancel();
    super.dispose();
  }
}
