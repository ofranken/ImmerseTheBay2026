import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models.dart';
import '../services/ar_bridge.dart';
import '../state/social.dart';
import '../theme/palette.dart';
import '../theme/theme.dart';
import '../widgets/paper.dart';
import 'collage_editor_screen.dart';
import 'hunts_screen.dart';
import 'studio_screen.dart';

class FriendsScreen extends StatelessWidget {
  const FriendsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final social = context.watch<Social>();
    return RefreshIndicator(
      onRefresh: social.refreshAll,
      child: ListView(padding: const EdgeInsets.fromLTRB(18, 12, 18, 32), children: [
        Text('FRIENDS', style: ScrappType.display(34)),
        const SizedBox(height: 10),
        const _AddFriend(),
        if (social.incoming.isNotEmpty) ...[
          const SectionTitle('Requests'),
          for (final r in social.incoming)
            Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: PaperCard(child: Row(children: [
                const Icon(Icons.person_add_alt_1_rounded),
                const SizedBox(width: 10),
                Expanded(child: Text(r.from.displayName, style: const TextStyle(fontWeight: FontWeight.w800))),
                ScrappButton(label: 'Accept', onPressed: () async {
                  try {
                    await social.accept(r.requestId);
                  } catch (e) {
                    if (context.mounted) toast(context, '$e');
                  }
                }),
              ])),
            ),
        ],
        const SectionTitle('Inbox'),
        if (social.inbox.isEmpty) const EmptyNote(icon: Icons.inbox_rounded, title: 'Nothing yet', body: 'Stickers, collages and hunts friends send you appear here.'),
        for (final e in social.inbox) Padding(padding: const EdgeInsets.only(bottom: 10), child: _InboxCard(entry: e)),
        const SectionTitle('Your friends'),
        if (social.friends.isEmpty) const Text('Add friends by username.', style: TextStyle(color: Palette.inkSoft)),
        Wrap(spacing: 8, runSpacing: 8, children: [for (final f in social.friends) Pill(label: '@${f.username}', icon: Icons.person_rounded)]),
      ]),
    );
  }
}

class _AddFriend extends StatefulWidget {
  const _AddFriend();
  @override
  State<_AddFriend> createState() => _AddFriendState();
}

class _AddFriendState extends State<_AddFriend> {
  final c = TextEditingController();

  @override
  Widget build(BuildContext context) => Row(children: [
        Expanded(child: TextField(controller: c, decoration: const InputDecoration(labelText: 'Add by username', prefixText: '@'))),
        const SizedBox(width: 8),
        ScrappButton(
          label: 'Add',
          onPressed: () async {
            try {
              final name = c.text.trim().replaceFirst(RegExp(r'^@+'), '');
              if (name.isEmpty) return;
              final status = await context.read<Social>().addFriend(name);
              c.clear();
              if (context.mounted) toast(context, status == 'accepted' ? 'You are now friends' : 'Request sent');
              if (context.mounted) await context.read<Social>().refreshFriends();
            } catch (e) {
              if (context.mounted) toast(context, '$e');
            }
          },
        ),
      ]);
}

class _InboxCard extends StatelessWidget {
  const _InboxCard({required this.entry});
  final InboxEntry entry;

  String _anchorHint(AnchorSpec a) => switch (a.mode) {
        'object' => 'Hold up ${_article(a.objectClass ?? 'object')} ${a.objectClass ?? 'object'} to see it',
        'image' => 'Find the original object to see it',
        'geo' => 'Appears where it was made',
        _ => 'Place it on any surface',
      };

  String _article(String w) => 'aeiou'.contains(w[0]) ? 'an' : 'a';

  Future<void> _open(BuildContext context) async {
    final social = context.read<Social>();
    social.markSeen(entry).catchError((_) {}); // best effort: opening the item matters more
    switch (entry.kind) {
      case 'sticker':
        final s = Sticker(entry.item);
        final a = entry.anchor;
        if (s.imageUrl == null) {
          if (context.mounted) toast(context, 'That sticker is no longer available.');
          return;
        }
        await ArBridge.open(
          title: 'From ${entry.fromName}',
          instructions: _anchorHint(a),
          items: [ArItem(id: s.id, imageUrl: s.imageUrl!, anchor: a, title: s.title, targetUrl: a.targetUrl)],
        );
      case 'collage':
        await Navigator.push(context, MaterialPageRoute(builder: (_) => CollageEditorScreen(collage: Collage(entry.item))));
      case 'mesh':
        final m = MeshJob(entry.item);
        if (!m.done) {
          if (context.mounted) toast(context, 'That 3D model is no longer available.');
          return;
        }
        if (context.mounted) await Navigator.push(context, MaterialPageRoute(builder: (_) => MeshPreviewScreen(mesh: m)));
      case 'hunt':
        // The inbox already carries the whole hunt; the play screen also loads it fresh and can retry.
        social.replaceFromJson(Map<String, dynamic>.from(entry.item));
        if (context.mounted) await Navigator.push(context, MaterialPageRoute(builder: (_) => HuntPlayScreen(huntId: entry.item['id'])));
    }
  }

  @override
  Widget build(BuildContext context) {
    final item = entry.item;
    final preview = switch (entry.kind) {
      'sticker' => StickerImage(url: item['image_url'], size: 64),
      'collage' => ClipRRect(borderRadius: BorderRadius.circular(10), child: Image.network(item['thumbnail_url'] ?? '', width: 64, height: 64, fit: BoxFit.cover, errorBuilder: (_, __, ___) => const Icon(Icons.layers_rounded, size: 40))),
      'mesh' => ClipRRect(borderRadius: BorderRadius.circular(10), child: Image.network(item['thumbnail_url'] ?? '', width: 64, height: 64, fit: BoxFit.cover, errorBuilder: (_, __, ___) => const Icon(Icons.view_in_ar_rounded, size: 40))),
      _ => const Icon(Icons.travel_explore_rounded, size: 48),
    };
    final what = switch (entry.kind) { 'sticker' => 'a sticker', 'collage' => 'a collage', 'mesh' => 'a 3D model', 'hunt' => 'a hunt: ${item['title'] ?? ''}', _ => entry.kind };
    return PaperCard(
      color: entry.seen ? Palette.card : Palette.teal,
      onTap: () => _open(context),
      child: Row(children: [
        preview,
        const SizedBox(width: 12),
        Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('${entry.fromName} sent $what', style: const TextStyle(fontWeight: FontWeight.w900)),
          if (entry.message != null) Text('"${entry.message}"', style: const TextStyle(fontStyle: FontStyle.italic)),
          if (entry.kind == 'sticker') Text(_anchorHint(entry.anchor), style: const TextStyle(color: Palette.inkSoft)),
        ])),
        Icon(entry.kind == 'sticker' ? Icons.view_in_ar_rounded : Icons.chevron_right_rounded),
      ]),
    );
  }
}
