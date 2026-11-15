import 'package:fake_async/fake_async.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:scrapp/models.dart';
import 'package:scrapp/state/social.dart';

import 'fakes.dart';

Map<String, dynamic> user(String id, String name) => {'id': id, 'username': name, 'display_name': name};

FakeApi _api({List incoming = const [], List friends = const [], List inbox = const [], List hunts = const []}) => FakeApi()
  ..routes.addAll({
    'GET /friends': {'friends': friends, 'incoming': incoming},
    'GET /shares/inbox': inbox,
    'GET /hunts': hunts,
  });

void main() {
  test('friend requests: incoming list, accept refreshes friends', () async {
    final api = _api(incoming: [
      {'request_id': 'r1', 'from': user('u2', 'bob')},
    ]);
    final social = Social(() => api);
    await social.refreshFriends();
    expect(social.incoming.single.from.username, 'bob');
    expect(social.unseen, 1); // a pending request counts as something new

    api.routes['POST /friends/r1/accept'] = {'status': 'accepted'};
    api.routes['GET /friends'] = {'friends': [user('u2', 'bob')], 'incoming': []};
    await social.accept('r1');
    expect(social.incoming, isEmpty);
    expect(social.friends.map((f) => f.username), ['bob']);
  });

  test('addFriend sends the username and returns the server status', () async {
    final api = _api();
    Object? sent;
    api.routes['POST /friends/request'] = (body) {
      sent = body;
      return {'status': 'accepted'};
    };
    final social = Social(() => api);
    expect(await social.addFriend('bob'), 'accepted');
    expect(sent, {'username': 'bob'});
  });

  test('inbox: parses every kind, counts unread, markSeen clears the badge', () async {
    final api = _api(inbox: [
      {'id': 's1', 'kind': 'sticker', 'seen_at': null, 'from': user('u2', 'bob'), 'anchor': {'mode': 'object', 'object_class': 'apple'}, 'item': {'id': 'st', 'image_url': 'http://x/a.png'}},
      {'id': 's2', 'kind': 'mesh', 'seen_at': null, 'from': user('u2', 'bob'), 'item': {'id': 'm', 'status': 'SUCCEEDED', 'glb_url': 'http://x/m.glb'}},
      {'id': 's3', 'kind': 'hunt', 'seen_at': '2026-11-14T00:00:00Z', 'from': user('u2', 'bob'), 'item': {'id': 'h', 'title': 'Art walk', 'items': []}},
    ]);
    final social = Social(() => api);
    await social.refreshInbox();
    expect(social.inbox.map((e) => e.kind), ['sticker', 'mesh', 'hunt']);
    expect(social.inbox[0].anchor.mode, 'object');
    expect(social.inbox[0].fromName, 'bob');
    expect(MeshJob(social.inbox[1].item).done, isTrue); // a received 3D model can be previewed
    expect(social.unseen, 2);

    api.routes['POST /shares/s1/seen'] = {'ok': true};
    await social.markSeen(social.inbox[0]);
    expect(social.unseen, 1);
    final calls = api.calls.length;
    await social.markSeen(social.inbox[0]); // already seen: no second request
    expect(api.calls.length, calls);
  });

  test('share posts kind, item, friends, anchor and message and returns the count', () async {
    final api = _api();
    Map? body;
    api.routes['POST /shares'] = (b) {
      body = b as Map;
      return {'shared': 2};
    };
    final social = Social(() => api);
    final n = await social.share(kind: 'mesh', itemId: 'm1', to: ['u2', 'u3'], message: 'look');
    expect(n, 2);
    expect(body!['kind'], 'mesh');
    expect(body!['item_id'], 'm1');
    expect(body!['to_user_ids'], ['u2', 'u3']);
    expect(body!['message'], 'look');
  });

  test('share errors reach the caller (not a friend)', () async {
    final api = _api();
    api.routes['POST /shares'] = (_) => throw Exception('You can only share with friends');
    final social = Social(() => api);
    expect(() => social.share(kind: 'hunt', itemId: 'h', to: ['u9']), throwsException);
  });

  test('startup retry and reset', () {
    fakeAsync((async) {
      final api = _api(friends: [user('u2', 'bob')])..failing = true;
      final social = Social(() => api);
      social.refreshAll().catchError((_) {});
      async.flushMicrotasks();
      expect(social.loadError, isNotNull);
      api.failing = false;
      async.elapse(const Duration(seconds: 3));
      expect(social.loadError, isNull);
      expect(social.friends.single.username, 'bob');

      social.reset(); // account switch: nothing from the previous user survives
      expect(social.friends, isEmpty);
      expect(social.inbox, isEmpty);
      social.dispose();
    });
  });

  test('a hunt from the inbox is usable immediately', () async {
    final social = Social(() => _api());
    social.replaceFromJson({'id': 'h1', 'title': 'Art walk', 'items': [], 'found_count': 0, 'total': 0});
    expect(social.hunts.single.title, 'Art walk');
    social.replaceFromJson({'id': 'h1', 'title': 'Art walk', 'items': [], 'found_count': 1, 'total': 3});
    expect(social.hunts, hasLength(1)); // replaced, not duplicated
    expect(social.hunts.single.foundCount, 1);
  });
}
