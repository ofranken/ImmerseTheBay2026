import 'package:flutter_test/flutter_test.dart';
import 'package:scrapp/models.dart';
import 'package:scrapp/services/collage_ar.dart';

void main() {
  final scene = <String, dynamic>{
    'version': 1,
    'items': [
      {'id': 'a', 'kind': 'sticker', 'ref_id': 's1', 'title': 'Mug', 'position': [0.1, 0.6, 0], 'quaternion': [0, 0.7071, 0, 0.7071], 'scale': 1.5},
      {'id': 'b', 'kind': 'mesh', 'ref_id': 'm1', 'title': 'Shoe', 'position': [0, 0, 0.2], 'quaternion': [0, 0, 0, 1], 'scale': 1},
      {'id': 'c', 'kind': 'sticker', 'ref_id': 'gone', 'title': 'Deleted'},
    ],
  };

  test('resolves URLs by item id first, then by ref id, and drops items without one', () {
    final items = collageArItems(scene,
        urlByItemId: {'a': 'http://signed/a.png'}, urlByRefId: {'s1': 'http://lib/s1.png', 'm1': 'http://lib/m1.glb'});
    expect(items.map((e) => e['id']), ['a', 'b']);
    expect(items[0]['url'], 'http://signed/a.png');
    expect(items[1]['url'], 'http://lib/m1.glb');
    expect(items[1]['kind'], 'mesh');
  });

  test('keeps transforms as doubles and fills gaps sensibly', () {
    final items = collageArItems({
      'items': [
        {'id': 'x', 'kind': 'sticker', 'url': 'http://u/x.png', 'position': [1, 2], 'scale': 2},
        {'id': 'y', 'kind': 'weird', 'url': 'http://u/y.png'},
      ],
    });
    expect(items[0]['position'], [1.0, 2.0, 0.0]);
    expect(items[0]['quaternion'], [0.0, 0.0, 0.0, 1.0]); // missing rotation = identity
    expect(items[0]['scale'], 2.0);
    expect(items[1]['kind'], 'sticker'); // unknown kinds draw as cards
    expect(items[1]['scale'], 1.0);
  });

  test('an item URL already in the scene wins', () {
    final items = collageArItems({
      'items': [
        {'id': 'x', 'kind': 'sticker', 'ref_id': 'r', 'url': 'http://scene/x.png'},
      ],
    }, urlByRefId: {'r': 'http://lib/r.png'});
    expect(items.single['url'], 'http://scene/x.png');
  });

  test('empty or malformed scenes give nothing to show', () async {
    expect(collageArItems({}), isEmpty);
    expect(collageArItems({'items': 'nope'}), isEmpty);
    expect(collageArItems({'items': [42, null]}), isEmpty);
    expect(await openCollageAr(title: 't', items: const []), isFalse);
  });

  test('url maps come from saved scenes and the library', () {
    expect(sceneUrls({'items': [
      {'id': 'a', 'url': 'http://a'},
      {'id': 'b', 'url': null},
      {'url': 'http://no-id'},
    ]}), {'a': 'http://a'});
    final lib = libraryUrls(
      [Sticker({'id': 's1', 'image_url': 'http://s1'}), Sticker({'id': 's2'})],
      [MeshJob({'id': 'm1', 'glb_url': 'http://m1'}), MeshJob({'id': 'm2', 'status': 'PENDING'})],
    );
    expect(lib, {'s1': 'http://s1', 'm1': 'http://m1'});
  });
}
