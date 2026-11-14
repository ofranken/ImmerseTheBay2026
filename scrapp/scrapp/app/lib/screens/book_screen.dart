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
  bool received = false;

  @override
  Widget build(BuildContext context) {
    final lib = context.watch<Library>();
    final list = received ? lib.received : lib.stickers;
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
              if (list.isEmpty) ...[
                const SizedBox(height: 16),
                EmptyNote(
                  icon: Icons.style_rounded,
                  title: received ? 'No gifts yet' : 'Your book is empty',
                  body: received ? 'Stickers friends send you land here.' : 'Every "scrapbook that" turns the things in view into stickers.',
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
                        if (s.isHero) const Positioned(right: 0, top: 0, child: Icon(Icons.star_rounded, color: Palette.tealDeep, size: 18)),
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
