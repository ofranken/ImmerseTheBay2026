import 'package:flutter_test/flutter_test.dart';
import 'package:scrapp/collage_background.dart';

void main() {
  test('every preset in the picker passes the same rules the server enforces', () {
    for (final p in backgroundPresets) {
      expect(isValidBackground(p.json), isTrue, reason: p.label);
    }
    expect(backgroundPresets.map((p) => p.label).toSet().length, backgroundPresets.length, reason: 'labels are unique');
    expect(backgroundPresets.first.json, isNull, reason: 'the first choice restores the default look');
  });

  test('bad backgrounds are caught before they are sent', () {
    for (final bad in <Map<String, dynamic>>[
      {'type': 'color'},
      {'type': 'color', 'value': 'red'},
      {'type': 'color', 'value': '#12345'},
      {'type': 'gradient', 'colors': ['#ffffff']},
      {'type': 'gradient', 'colors': ['#ffffff', 'blue']},
      {'type': 'gradient', 'colors': ['#111111', '#222222'], 'angle': 400},
      {'type': 'photo'},
      {'type': 'photo', 'ref_id': ''},
      {'type': 'video'},
    ]) {
      expect(isValidBackground(bad), isFalse, reason: '$bad');
    }
    expect(isValidBackground(null), isTrue);
  });

  test('photo backgrounds carry the capture id, and the live url only when there is one', () {
    expect(photoBackground('c1', 'http://x/c1.jpg'), {'type': 'photo', 'ref_id': 'c1', 'url': 'http://x/c1.jpg'});
    expect(photoBackground('c1', null), {'type': 'photo', 'ref_id': 'c1'});
    expect(isValidBackground(photoBackground('c1', null)), isTrue);
  });

  test('sameBackground ignores the live photo url and tells choices apart', () {
    expect(sameBackground(null, null), isTrue);
    expect(sameBackground(null, {'type': 'paper'}), isFalse);
    expect(sameBackground({'type': 'paper'}, {'type': 'paper'}), isTrue);
    expect(sameBackground({'type': 'color', 'value': '#111111'}, {'type': 'color', 'value': '#111111'}), isTrue);
    expect(sameBackground({'type': 'color', 'value': '#111111'}, {'type': 'color', 'value': '#222222'}), isFalse);
    expect(sameBackground(photoBackground('c1', 'http://old'), photoBackground('c1', 'http://new')), isTrue);
    expect(sameBackground(photoBackground('c1', null), photoBackground('c2', null)), isFalse);
    final sunset = backgroundPresets.firstWhere((p) => p.label == 'Sunset').json;
    final night = backgroundPresets.firstWhere((p) => p.label == 'Night').json;
    expect(sameBackground(sunset, sunset), isTrue);
    expect(sameBackground(sunset, night), isFalse);
  });
}
