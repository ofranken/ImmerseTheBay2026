import 'package:fake_async/fake_async.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:scrapp/state/library.dart';

import 'fakes.dart';

Map<String, dynamic> sticker(String id, {bool starred = false}) =>
    {'id': id, 'owner_id': 'me', 'capture_id': 'c1', 'image_url': 'http://x/$id.png', 'starred': starred};

FakeApi _api() => FakeApi()
  ..routes.addAll({
    'GET /stickers': [sticker('s1')],
    'GET /captures': [],
    'GET /collages': [],
    'GET /meshes': [],
  });

void main() {
  test('first load fails offline, then retries by itself and fills the book', () {
    fakeAsync((async) {
      final api = _api()..failing = true;
      final lib = Library(() => api);

      lib.refreshAll().catchError((_) {});
      async.flushMicrotasks();
      expect(lib.stickers, isEmpty);
      expect(lib.loadError, isNotNull);

      async.elapse(const Duration(seconds: 3)); // first retry fires at 2s, still offline
      expect(lib.loadError, isNotNull);

      api.failing = false; // network comes back
      async.elapse(const Duration(seconds: 6)); // second retry (4s later)
      expect(lib.loadError, isNull);
      expect(lib.stickers.map((s) => s.id), ['s1']);

      final calls = api.calls.length;
      async.elapse(const Duration(minutes: 2)); // no more retries once it works
      expect(api.calls.length, calls);
      lib.dispose();
    });
  });

  test('reset forgets the previous account and stops retrying', () {
    fakeAsync((async) {
      final api = _api()..failing = true;
      final lib = Library(() => api);
      lib.refreshAll().catchError((_) {});
      async.flushMicrotasks();
      lib.reset();
      final calls = api.calls.length;
      async.elapse(const Duration(minutes: 1));
      expect(api.calls.length, calls);
      expect(lib.stickers, isEmpty);
      expect(lib.loadError, isNull);
      lib.dispose();
    });
  });

  test('starring updates the sticker in place', () async {
    final api = _api()..routes['PATCH /stickers/s1'] = (body) => sticker('s1', starred: (body as Map)['starred'] == true);
    final lib = Library(() => api);
    await lib.refreshAll();
    final s = lib.stickers.first;
    expect(s.starred, isFalse);
    await lib.setStarred(s, true);
    expect(lib.stickers.first.starred, isTrue);
    lib.dispose();
  });
}
