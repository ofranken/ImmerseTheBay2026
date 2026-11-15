import 'package:flutter/foundation.dart';

import '../models.dart';
import '../services/api.dart';

/// Friends, the share inbox and scavenger hunts.
class Social extends ChangeNotifier {
  Social(this._api);
  final ApiClient Function() _api;
  ApiClient get api => _api();

  List<AppUser> friends = [];
  List<({String requestId, AppUser from})> incoming = [];
  List<InboxEntry> inbox = [];
  List<Hunt> hunts = [];

  int get unseen => inbox.where((e) => !e.seen).length + incoming.length;

  Future<void> refreshAll() => Future.wait([refreshFriends(), refreshInbox(), refreshHunts()]);

  Future<void> refreshFriends() async {
    final r = Map<String, dynamic>.from(await api.get('/friends'));
    friends = (r['friends'] as List).map((e) => AppUser.fromJson(Map<String, dynamic>.from(e))).toList();
    incoming = (r['incoming'] as List)
        .map((e) => (requestId: e['request_id'] as String, from: AppUser.fromJson(Map<String, dynamic>.from(e['from']))))
        .toList();
    notifyListeners();
  }

  Future<String> addFriend(String username) async => (await api.post('/friends/request', {'username': username}))['status'];

  Future<void> accept(String requestId) async {
    await api.post('/friends/$requestId/accept');
    await refreshFriends();
  }

  Future<void> refreshInbox() async {
    final r = await api.get('/shares/inbox') as List;
    inbox = r.map((e) => InboxEntry(Map<String, dynamic>.from(e))).toList();
    notifyListeners();
  }

  Future<void> markSeen(InboxEntry e) async {
    if (e.seen) return;
    await api.post('/shares/${e.id}/seen');
    e.j['seen_at'] = DateTime.now().toIso8601String();
    notifyListeners();
  }

  Future<int> share({required String kind, required String itemId, required List<String> to, AnchorSpec? anchor, String? message}) async {
    final r = await api.post('/shares', {
      'kind': kind,
      'item_id': itemId,
      'to_user_ids': to,
      if (anchor != null) 'anchor': anchor.toJson(),
      if (message != null && message.isNotEmpty) 'message': message,
    });
    return (r['shared'] as num).toInt();
  }

  Future<void> refreshHunts() async {
    final r = await api.get('/hunts') as List;
    hunts = r.map((e) => Hunt(Map<String, dynamic>.from(e))).toList();
    notifyListeners();
  }

  Future<Hunt> createHunt(String title, String? description, List<Map<String, dynamic>> items) async {
    final h = Hunt(Map<String, dynamic>.from(await api.post('/hunts', {'title': title, 'description': description, 'items': items})));
    hunts.insert(0, h);
    notifyListeners();
    return h;
  }

  Future<Hunt> startHunt(String id) async => _replace(Hunt(Map<String, dynamic>.from(await api.post('/hunts/$id/start'))));

  Future<Hunt> markFound(String huntId, String itemId) async =>
      _replace(Hunt(Map<String, dynamic>.from(await api.post('/hunts/$huntId/items/$itemId/found'))));

  /// Loads one hunt (e.g. opened from the share inbox before the list has it).
  Future<Hunt> fetchHunt(String id) async => _replace(Hunt(Map<String, dynamic>.from(await api.get('/hunts/$id'))));

  Future<void> deleteHunt(String id) async {
    await api.delete('/hunts/$id');
    hunts.removeWhere((h) => h.id == id);
    notifyListeners();
  }

  Future<List<HuntPlayer>> huntPlayers(String id) async {
    final r = Map<String, dynamic>.from(await api.get('/hunts/$id/progress'));
    return (r['players'] as List).map((e) => HuntPlayer(Map<String, dynamic>.from(e))).toList();
  }

  Hunt replaceFromJson(Map<String, dynamic> j) => _replace(Hunt(j));

  Hunt _replace(Hunt h) {
    final i = hunts.indexWhere((x) => x.id == h.id);
    if (i >= 0) {
      hunts[i] = h;
    } else {
      hunts.insert(0, h);
    }
    notifyListeners();
    return h;
  }
}
