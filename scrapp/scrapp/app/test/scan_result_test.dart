import 'package:flutter_test/flutter_test.dart';
import 'package:scrapp/models.dart';

void main() {
  test('matched scan names the find', () {
    final r = ScanResult({'matched': true, 'item': {'title': 'Mouse'}, 'scan': {'status': 'matched'}});
    expect(r.status, 'matched');
    expect(r.message, 'Matched "Mouse"!');
  });
  test('close scan tells the player what to do', () {
    final r = ScanResult({'matched': false, 'scan': {'status': 'close', 'best_title': 'C4 can', 'score': 0.4}});
    expect(r.status, 'close');
    expect(r.message, contains('C4 can'));
    expect(r.message, contains('hold steady'));
  });
  test('too far is explained, not silent', () {
    final r = ScanResult({'matched': false, 'scan': {'status': 'none', 'out_of_range': 2, 'reason': 'all remaining items are too far away'}});
    expect(r.message, contains('too far'));
  });
  test('plain miss still gives guidance', () {
    expect(ScanResult({'matched': false}).message, contains('Fill the frame'));
  });
}
