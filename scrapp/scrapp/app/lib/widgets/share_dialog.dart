import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../state/social.dart';
import '../theme/palette.dart';
import 'paper.dart';

/// "Send to friends" for items that need no anchor choice (hunts, 3D models, collages).
/// Returns how many friends it was sent to (0 if cancelled or nothing sent).
Future<int> shareWithFriends(BuildContext context, {required String kind, required String itemId, required String title}) async {
  final social = context.read<Social>();
  try {
    await social.refreshFriends();
  } catch (e) {
    if (context.mounted) toast(context, 'Could not load your friends: $e');
    return 0;
  }
  if (!context.mounted) return 0;
  if (social.friends.isEmpty) {
    toast(context, 'Add a friend first (Friends tab), then send it to them.');
    return 0;
  }
  final picked = <String>{};
  final ok = await showDialog<bool>(
    context: context,
    builder: (ctx) => StatefulBuilder(
      builder: (ctx, set) => AlertDialog(
        backgroundColor: Palette.card,
        title: Text(title),
        content: Wrap(spacing: 8, children: [
          for (final f in social.friends)
            FilterChip(label: Text(f.displayName), selected: picked.contains(f.id), onSelected: (v) => set(() => v ? picked.add(f.id) : picked.remove(f.id))),
        ]),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
          TextButton(onPressed: picked.isEmpty ? null : () => Navigator.pop(ctx, true), child: const Text('Send')),
        ],
      ),
    ),
  );
  if (ok != true || picked.isEmpty || !context.mounted) return 0;
  try {
    final n = await social.share(kind: kind, itemId: itemId, to: picked.toList());
    if (context.mounted) toast(context, 'Sent to $n ${n == 1 ? 'friend' : 'friends'}');
    return n;
  } catch (e) {
    if (context.mounted) toast(context, '$e');
    return 0;
  }
}
