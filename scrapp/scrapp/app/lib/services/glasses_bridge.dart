import 'dart:async';
import 'dart:convert';

import 'package:flutter/services.dart';

/// Dart side of the Kotlin glasses bridge (android/.../glasses/GlassesChannel.kt).
/// The native side owns the Meta Wearables session inside a foreground service so voice and
/// capture-button triggers keep working with the phone in a pocket.
class GlassesBridge {
  static const _m = MethodChannel('scrapp/glasses');
  static const _e = EventChannel('scrapp/glasses/events');

  static Stream<Map<String, dynamic>>? _events;
  static Stream<Map<String, dynamic>> get events =>
      _events ??= _e.receiveBroadcastStream().map((e) => Map<String, dynamic>.from(e as Map)).asBroadcastStream();

  static Future<Map<String, dynamic>> _call(String method, [Map<String, dynamic>? args]) async {
    final r = await _m.invokeMethod<dynamic>(method, args);
    return r is Map ? Map<String, dynamic>.from(r) : <String, dynamic>{'result': r};
  }

  /// Requests Android Bluetooth permissions and initializes the Wearables SDK.
  static Future<Map<String, dynamic>> initialize() => _call('initialize');
  static Future<Map<String, dynamic>> status() => _call('status');
  static Future<void> register() => _call('register');
  static Future<void> unregister() => _call('unregister');

  /// permission: "camera" or "microphone". Opens the Meta AI app's grant flow.
  static Future<String> requestPermission(String permission) async =>
      (await _call('requestPermission', {'permission': permission}))['result']?.toString() ?? 'error';

  /// Starts the foreground service, the device session, voice ("scrap that") and the capture button.
  static Future<void> arm({bool warmCamera = true, bool voice = true, bool button = true}) =>
      _call('arm', {'warmCamera': warmCamera, 'voice': voice, 'button': button});
  static Future<void> disarm() => _call('disarm');
  static Future<void> captureNow() => _call('captureNow', {'trigger': 'app'});

  /// While a hunt is active, glasses captures are tagged with its id so the app checks them.
  static Future<void> setActiveHunt(String? huntId, String? title) => _call('setHunt', {'huntId': huntId, 'title': title});

  /// Spoken through the glasses speakers (they are the phone's Bluetooth audio route).
  static Future<void> speak(String text) => _call('speak', {'text': text});

  /// Captures saved natively but not yet uploaded (outbox survives app restarts).
  static Future<List<PendingCapture>> pendingCaptures() async {
    final r = await _m.invokeMethod<List<dynamic>>('pendingCaptures');
    return (r ?? []).map((e) => PendingCapture.fromMap(Map<String, dynamic>.from(e as Map))).toList();
  }

  static Future<void> ackCapture(String id) => _call('ackCapture', {'id': id});

  /// Debug only: Meta's MockDeviceKit simulates paired glasses (no hardware needed).
  static Future<void> setMockDevice(bool enabled) => _call('enableMock', {'enabled': enabled});
  static Future<void> simulateTranscript(String text) => _call('simulateTranscript', {'text': text});
  static Future<bool> consumeVoiceLaunch() async => (await _call('consumeLaunchIntent'))['result'] == true;
}

class PendingCapture {
  PendingCapture({required this.id, required this.path, required this.meta});
  final String id;
  final String path;
  final Map<String, dynamic> meta;

  factory PendingCapture.fromMap(Map<String, dynamic> m) => PendingCapture(
        id: m['id'] as String,
        path: m['path'] as String,
        meta: Map<String, dynamic>.from(jsonDecode(m['meta'] as String? ?? '{}') as Map),
      );
}
