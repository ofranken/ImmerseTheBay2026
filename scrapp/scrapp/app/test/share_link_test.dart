import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:scrapp/state/library.dart';
import 'package:scrapp/widgets/share_link_sheet.dart';

import 'fakes.dart';

void main() {
  test('qrUrlFor points at the server-made QR image of the link', () {
    expect(qrUrlFor('https://scrapp.nmagic.dev/c/abc123'), 'https://scrapp.nmagic.dev/c/abc123/qr.png');
    expect(qrUrlFor('https://scrapp.nmagic.dev/c/abc123/'), 'https://scrapp.nmagic.dev/c/abc123/qr.png'); // no double slash
  });

  test('publishCollage returns the public link the server made', () async {
    final api = FakeApi()..routes['POST /collages/c1/publish'] = {'url': 'https://scrapp.nmagic.dev/c/tok'};
    expect(await Library(() => api).publishCollage('c1'), 'https://scrapp.nmagic.dev/c/tok');
  });

  test('saving a collage sends the AR model only when there is one', () async {
    final collage = {'id': 'c1', 'title': 'Trip', 'scene': {'items': []}, 'has_scene_glb': true};
    final api = FakeApi()
      ..routes['POST /collages'] = collage
      ..routes['PUT /collages/c1'] = collage;
    final lib = Library(() => api);
    final png = Uint8List.fromList([1, 2, 3]);

    await lib.saveCollage(title: 'Trip', sceneJson: '{"items":[]}', png: png, glb: Uint8List.fromList([0x67, 0x6c, 0x54, 0x46]));
    expect(api.uploads.last.method, 'POST');
    expect(api.uploads.last.files, ['thumbnail', 'scene_glb']);

    await lib.saveCollage(id: 'c1', title: 'Trip', sceneJson: '{"items":[]}', png: png); // the AR export failed or was skipped
    expect(api.uploads.last.method, 'PUT');
    expect(api.uploads.last.files, ['thumbnail']); // the collage still saves, just without an AR model
    expect(api.uploads.last.fields['title'], 'Trip');
  });
}
