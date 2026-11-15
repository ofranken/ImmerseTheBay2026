import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../models.dart';
import '../services/api.dart';

/// Pass the backend at build time: flutter run --dart-define=API_BASE=http://192.168.1.50:8000
const _defaultApi = String.fromEnvironment('API_BASE', defaultValue: 'http://10.0.2.2:8000');

class GlassesSettings {
  bool warmCamera = true; // keep a low-fps stream open so "scrapbook that" captures in ~1 s
  bool voice = true;
  bool button = true;
  bool mockDevice = false;
}

class AppState extends ChangeNotifier {
  late SharedPreferences _prefs;
  final api = ApiClient(baseUrl: _defaultApi);
  AppUser? user;
  bool ready = false;
  final glasses = GlassesSettings();

  bool get signedIn => user != null;

  Future<void> init() async {
    _prefs = await SharedPreferences.getInstance();
    api.baseUrl = _prefs.getString('api_base') ?? _defaultApi;
    api.token = _prefs.getString('token');
    glasses
      ..warmCamera = _prefs.getBool('g_warm') ?? true
      ..voice = _prefs.getBool('g_voice') ?? true
      ..button = _prefs.getBool('g_button') ?? true
      ..mockDevice = _prefs.getBool('g_mock') ?? false;
    final cached = _prefs.getString('user');
    if (api.token != null && cached != null) {
      user = AppUser.fromJson(jsonDecode(cached));
      try {
        user = AppUser.fromJson(await api.get('/auth/me'));
      } on ApiException catch (e) {
        if (e.status == 401) await signOut();
      } catch (_) {/* offline: keep cached user */}
    }
    ready = true;
    notifyListeners();
  }

  Future<void> _session(Map<String, dynamic> r) async {
    api.token = r['token'];
    user = AppUser.fromJson(Map<String, dynamic>.from(r['user']));
    await _prefs.setString('token', api.token!);
    await _prefs.setString('user', jsonEncode(r['user']));
    notifyListeners();
  }

  Future<void> signIn(String who, String password) async =>
      _session(await api.post('/auth/login', {'username_or_email': who, 'password': password}));

  Future<void> register(String username, String email, String password, {String? inviteCode}) async =>
      _session(await api.post('/auth/register', {
        'username': username,
        'email': email,
        'password': password,
        if (inviteCode != null && inviteCode.trim().isNotEmpty) 'invite_code': inviteCode.trim(),
      }));

  /// The hunt being played with the glasses, kept across app restarts.
  String? get activeHuntId => _prefs.getString('active_hunt');
  Future<void> saveActiveHunt(String? id) async =>
      id == null ? await _prefs.remove('active_hunt') : await _prefs.setString('active_hunt', id);

  Future<void> signOut() async {
    await _prefs.remove('active_hunt');
    api.token = null;
    user = null;
    await _prefs.remove('token');
    await _prefs.remove('user');
    notifyListeners();
  }

  Future<void> setApiBase(String url) async {
    api.baseUrl = url.trim().replaceAll(RegExp(r'/+$'), '');
    await _prefs.setString('api_base', api.baseUrl);
    notifyListeners();
  }

  Future<void> saveGlassesSettings() async {
    await _prefs.setBool('g_warm', glasses.warmCamera);
    await _prefs.setBool('g_voice', glasses.voice);
    await _prefs.setBool('g_button', glasses.button);
    await _prefs.setBool('g_mock', glasses.mockDevice);
    notifyListeners();
  }
}
