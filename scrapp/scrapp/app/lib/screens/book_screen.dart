import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models.dart';
import '../state/library.dart';
import '../theme/palette.dart';
import '../theme/theme.dart';
import '../widgets/paper.dart';
import 'sticker_screen.dart';

/// The sticker book: your stickers grouped by place, plus ones friends sent you.
class BookScreen extends StatefulWidget {
  const BookScreen({super.key});
  @override
  State<BookScreen> createState() => _BookScreenState();
}

class _BookScreenState extends State<BookScreen> {
  Future<void> _confirmDelete(BuildContext context, Library lib, Sticker s) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('Delete this sticker?'),
        content: const Text('This can\'t be undone.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
          TextButton(onPressed: () => Navigator.pop(context, true), child: const Text('Delete', style: TextStyle(color: Palette.danger))),
        ],
      ),
    );
    if (ok == true) await lib.deleteSticker(s.id);
  }

  bool received = false;
  bool starredOnly = true;

  @override
  Widget build(BuildContext context) {
    final lib = context.watch<Library>();
    final all = received ? lib.received : lib.stickers;
    final list = (starredOnly && !received) ? all.where((s) => s.starred).toList() : all;
    final groups = <String, List<Sticker>>{};
    for (final s in list) {
      groups.putIfAbsent(s.placeName?.isNotEmpty == true ? s.placeName! : 'Somewhere', () => []).add(s);
    }
    return RefreshIndicator(
      onRefresh: lib.refreshStickers,
      child: CustomScrollView(slivers: [
        SliverPadding(
          padding: const EdgeInsets.fromLTRB(18, 12, 18, 0),
          sliver: SliverToBoxAdapter(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('STICKER BOOK', style: ScrappType.display(34)),
              const SizedBox(height: 10),
              SegmentedButton<bool>(
                segments: const [
                  ButtonSegment(value: false, label: Text('Mine'), icon: Icon(Icons.auto_stories_rounded)),
                  ButtonSegment(value: true, label: Text('From friends'), icon: Icon(Icons.card_giftcard_rounded)),
                ],
                selected: {received},
                onSelectionChanged: (v) => setState(() => received = v.first),
              ),
              if (lib.loadError != null) ...[
                const SizedBox(height: 10),
                PaperCard(
                  color: Palette.card,
                  padding: const EdgeInsets.all(12),
                  child: Row(children: [
                    const Icon(Icons.cloud_off_rounded, color: Palette.danger),
                    const SizedBox(width: 10),
                    const Expanded(child: Text('Can\'t reach Scrapp. Retrying…', style: TextStyle(fontWeight: FontWeight.w700))),
                    TextButton(onPressed: () => lib.refreshAll().catchError((_) {}), child: const Text('Retry now')),
                  ]),
                ),
              ],
              if (!received) ...[
                const SizedBox(height: 10),
                SegmentedButton<bool>(
                  segments: const [
                    ButtonSegment(value: true, label: Text('Starred'), icon: Icon(Icons.star_rounded)),
                    ButtonSegment(value: false, label: Text('All'), icon: Icon(Icons.grid_view_rounded)),
                  ],
                  selected: {starredOnly},
                  onSelectionChanged: (v) => setState(() => starredOnly = v.first),
                ),
              ],
              if (list.isEmpty) ...[
                const SizedBox(height: 16),
                EmptyNote(
                  icon: Icons.style_rounded,
                  title: received ? 'No gifts yet' : (starredOnly && all.isNotEmpty ? 'No starred scrapps' : 'Your book is empty'),
                  body: received ? 'Stickers friends send you land here.' : (starredOnly && all.isNotEmpty ? 'Tap All, then star the ones you want here.' : 'Every "scrapbook that" turns the things in view into stickers.'),
                ),
              ],
            ]),
          ),
        ),
        for (final e in groups.entries) ...[
          SliverPadding(
            padding: const EdgeInsets.fromLTRB(18, 18, 18, 8),
            sliver: SliverToBoxAdapter(child: Row(children: [
              const Icon(Icons.place_rounded, color: Palette.inkSoft),
              const SizedBox(width: 6),
              Expanded(child: Text(e.key, style: const TextStyle(fontWeight: FontWeight.w900, fontSize: 18))),
              Text('${e.value.length}', style: const TextStyle(color: Palette.inkSoft, fontWeight: FontWeight.w800)),
            ])),
          ),
          SliverPadding(
            padding: const EdgeInsets.symmetric(horizontal: 18),
            sliver: SliverGrid.count(
              crossAxisCount: 3,
              mainAxisSpacing: 12,
              crossAxisSpacing: 12,
              children: [
                for (final s in e.value)
                  Semantics(
                    label: 'Sticker ${s.title}',
                    button: true,
                    child: PaperCard(
                      padding: const EdgeInsets.all(6),
                      radius: 18,
                      onTap: () => Navigator.push(context, MaterialPageRoute(builder: (_) => StickerScreen(sticker: s))),
                      child: Stack(children: [
                        Center(child: StickerImage(url: s.imageUrl, size: 96, heroTag: 'st-${s.id}')),
                        if (!received)
                          Positioned(
                            right: -6, top: -6,
                            child: IconButton(
                              tooltip: s.starred ? 'Remove star' : 'Star',
                              visualDensity: VisualDensity.compact,
                              icon: Icon(s.starred ? Icons.star_rounded : Icons.star_border_rounded, color: Palette.tealDeep, size: 24),
                              onPressed: () => lib.setStarred(s, !s.starred),
                            ),
                          ),
                        if (!received)
                          Positioned(
                            right: -6, bottom: -6,
                            child: IconButton(
                              tooltip: 'Delete',
                              visualDensity: VisualDensity.compact,
                              icon: const Icon(Icons.delete_outline_rounded, color: Palette.danger, size: 22),
                              onPressed: () => _confirmDelete(context, lib, s),
                            ),
                          ),
                      ]),
                    ),
                  ),
              ],
            ),
          ),
        ],
        const SliverToBoxAdapter(child: SizedBox(height: 32)),
      ]),
    );
  }
}
