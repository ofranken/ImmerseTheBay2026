import 'package:fake_async/fake_async.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:scrapp/models.dart';
import 'package:scrapp/state/library.dart';

import 'fakes.dart';

void main() {
  test('a 3D job that finishes while the app is open is announced exactly once', () {
    fakeAsync((async) {
      var polls = 0;
      final api = FakeApi()
        ..routes.addAll({
          'GET /stickers': [],
          'GET /captures': [],
          'GET /collages': [],
          'GET /meshes': [
            {'id': 'm1', 'status': 'IN_PROGRESS', 'stage': 'image', 'progress': 10, 'prompt': 'a frog'},
          ],
          'GET /meshes/m1': (_) {
            polls++;
            return polls < 2
                ? {'id': 'm1', 'status': 'IN_PROGRESS', 'stage': 'image', 'progress': 60, 'prompt': 'a frog'}
                : {'id': 'm1', 'status': 'SUCCEEDED', 'stage': 'image', 'progress': 100, 'prompt': 'a frog', 'glb_url': 'http://x/m1.glb'};
          },
        });
      final lib = Library(() => api);
      final announced = <MeshJob>[];
      lib.meshFinished.listen(announced.add);

      lib.refreshAll();
      async.flushMicrotasks();
      expect(lib.meshes.single.done, isFalse);

      async.elapse(const Duration(seconds: 7)); // first poll: still growing
      expect(announced, isEmpty);
      async.elapse(const Duration(seconds: 7)); // second poll: done
      expect(announced.map((m) => m.id), ['m1']);
      expect(announced.single.done, isTrue);

      async.elapse(const Duration(minutes: 1)); // finished jobs are not polled or announced again
      expect(announced, hasLength(1));
      lib.dispose();
    });
  });

  test('a failed 3D job is announced too', () {
    fakeAsync((async) {
      final api = FakeApi()
        ..routes.addAll({
          'GET /stickers': [],
          'GET /captures': [],
          'GET /collages': [],
          'GET /meshes': [
            {'id': 'm2', 'status': 'IN_PROGRESS', 'stage': 'image', 'progress': 5},
          ],
          'GET /meshes/m2': {'id': 'm2', 'status': 'FAILED', 'error': 'bad image'},
        });
      final lib = Library(() => api);
      final announced = <MeshJob>[];
      lib.meshFinished.listen(announced.add);
      lib.refreshAll();
      async.flushMicrotasks();
      async.elapse(const Duration(seconds: 7));
      expect(announced.single.failed, isTrue);
      lib.dispose();
    });
  });
}
