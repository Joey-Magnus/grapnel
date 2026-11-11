/* Hookshot-local Ocarina of Time achievements. IDs are persisted by Hookshot and never
   sent to RetroAchievements. Keep IDs 0-5 stable for existing progress files. */
#ifndef OOT_ACHIEVEMENTS_H
#define OOT_ACHIEVEMENTS_H

enum {
    OOT_ACH_MANUAL = 0,       /* requires a dedicated gameplay event tracker */
    OOT_ACH_ANY_ITEM = 1,     /* any of item1/item2/item3 is present */
    OOT_ACH_ITEM_COUNT = 2,   /* item1/item2/item3 count reaches threshold */
    OOT_ACH_ADULT = 3,        /* the game reports Adult Link */
    OOT_ACH_ALL_SONGS = 4     /* all twelve known song pouch items are present */
};

/* X(id, title, short description, trigger, threshold, item1, item2, item3)
   IDs 0-4 are the first local achievements shipped by Hookshot; ID 5 is its Navi original.
   The remaining entries complete the 97-achievement Ocarina of Time N64 base-set catalog. */
#define OOT_LOCAL_ACHIEVEMENTS(X) \
    X(0, "Bring Me to the Bottom of the Oceans", "Obtain the Iron Boots.", OOT_ACH_ANY_ITEM, 1, "Armor_Adult_HeavyBoot", "", "") \
    X(1, "A Breath of Fresh Air", "Obtain a Zora Tunic.", OOT_ACH_ANY_ITEM, 1, "Armor_Adult_Zora", "", "") \
    X(2, "Entrusted Mission", "Receive the Spiritual Stone of the Forest.", OOT_ACH_ANY_ITEM, 1, "Item_Stone_Forest", "", "") \
    X(3, "Rise and Shine!!", "Help Malon find her father.", OOT_ACH_ANY_ITEM, 1, "Item_Bottle", "Item_Bottle_Milk", "") \
    X(4, "A Royal Autograph", "Meet Princess Zelda for the first time.", OOT_ACH_ANY_ITEM, 1, "Item_Letter_Zelda", "Item_Chick", "Item_RoyalLetter") \
    X(5, "Hey, Listen me!", "Be woken up by Navi.", OOT_ACH_MANUAL, 0, "", "", "") \
    X(6, "Bunches of Twigs", "Increase your Deku Stick capacity.", OOT_ACH_MANUAL, 0, "", "", "") \
    X(7, "Spider Net", "Defeat Queen Gohma before she escapes.", OOT_ACH_MANUAL, 0, "", "", "") \
    X(8, "Sniper Fury", "Earn a prize at the child shooting gallery.", OOT_ACH_ANY_ITEM, 1, "Item_BulletBag_Large", "", "") \
    X(9, "Money Solves Everything", "Pay the guard to enter the courtyard.", OOT_ACH_MANUAL, 0, "", "", "") \
    X(10, "Troublemaker", "Anger a guard inside Hyrule Castle.", OOT_ACH_MANUAL, 0, "", "", "") \
    X(11, "Shield Raider", "Find the Hylian Shield for free.", OOT_ACH_MANUAL, 0, "", "", "") \
    X(12, "Catch Me If You Can", "Win Anju's Kakariko Cucco challenge.", OOT_ACH_MANUAL, 0, "", "", "") \
    X(13, "Cuccos' Revenge", "Draw the Cuccos' full wrath.", OOT_ACH_MANUAL, 0, "", "", "") \
    X(14, "A Man's Best Friend", "Collect 10 Gold Skulltula tokens.", OOT_ACH_ITEM_COUNT, 10, "Item_Token_Gold", "", "") \
    X(15, "Dance Into the Fire", "Visit Darunia and receive his gift.", OOT_ACH_ANY_ITEM, 1, "Item_Gauntlet_Goron", "", "") \
    X(16, "Bullseye!!", "Earn the Bullet Bag upgrade in the Lost Woods.", OOT_ACH_ANY_ITEM, 1, "Item_BulletBag_Medium", "", "") \
    X(17, "You Can Be a Star", "Win the Lost Woods Ocarina game.", OOT_ACH_MANUAL, 0, "", "", "") \
    X(18, "Super Cucco Catching", "Win Talon's Cucco challenge.", OOT_ACH_MANUAL, 0, "", "", "") \
    X(19, "You Make Me Feel So Good", "Bottle fresh milk from a cow.", OOT_ACH_ANY_ITEM, 1, "Item_Bottle_Milk", "", "") \
    X(20, "Happy Mask Salesman", "Finish the Happy Mask quest.", OOT_ACH_ANY_ITEM, 1, "Armor_Child_Mask_Truth", "Item_Mask_Truth", "") \
    X(21, "A Pretty Face", "Increase your Deku Stick capacity again.", OOT_ACH_MANUAL, 0, "", "", "") \
    X(22, "Bombalicious", "Defeat King Dodongo without bag bombs.", OOT_ACH_MANUAL, 0, "", "", "") \
    X(23, "Soul Brothers", "Receive the Spiritual Stone of Fire.", OOT_ACH_ANY_ITEM, 1, "Item_Stone_Fire", "", "") \
    X(24, "You Spin Me Round", "Learn the Spin Attack technique.", OOT_ACH_MANUAL, 0, "", "", "") \
    X(25, "Walking on a Tightrope", "Open a chest in Goron City's boulder room.", OOT_ACH_MANUAL, 0, "", "", "") \
    X(26, "Roll Roll and Away", "Earn the Bomb Bag upgrade in Goron City.", OOT_ACH_ANY_ITEM, 1, "Item_BombBag_Medium", "Item_BombBag_Large", "") \
    X(27, "Bombchu Bowling Star", "Win the Bomb Bag upgrade at Bombchu Bowling.", OOT_ACH_ANY_ITEM, 1, "Item_BombBag_Large", "", "") \
    X(28, "Mouse Ka-Boom", "Obtain Bombchus.", OOT_ACH_ANY_ITEM, 1, "Item_Bombchu", "", "") \
    X(29, "Who Let the Dogs Out", "Help a woman find her lost dog.", OOT_ACH_MANUAL, 0, "", "", "") \
    X(30, "On Fire", "Learn Din's Fire.", OOT_ACH_ANY_ITEM, 1, "Item_DinFire", "", "") \
    X(31, "Stocking Nuts", "Increase your Deku Nut capacity.", OOT_ACH_MANUAL, 0, "", "", "") \
    X(32, "Magic Beans", "Obtain a Magic Bean.", OOT_ACH_ANY_ITEM, 1, "Item_MagicBean", "", "") \
    X(33, "The Way the World Learns to Dive", "Win Zora's diving challenge.", OOT_ACH_ANY_ITEM, 1, "Item_Scale_Silver", "Item_Scale_Gold", "") \
    X(34, "Take Me Away", "Learn Farore's Wind.", OOT_ACH_ANY_ITEM, 1, "Item_FaroreWind", "", "") \
    X(35, "Rolling Thunder", "Defeat Barinade without taking a hit.", OOT_ACH_MANUAL, 0, "", "", "") \
    X(36, "Wedding Band", "Receive the Spiritual Stone of Water.", OOT_ACH_ANY_ITEM, 1, "Item_Stone_Water", "", "") \
    X(37, "Fishing Lessons", "Catch a 10-pound fish as a child.", OOT_ACH_MANUAL, 0, "", "", "") \
    X(38, "A Horrible Face", "Increase your Deku Nut capacity again.", OOT_ACH_MANUAL, 0, "", "", "") \
    X(39, "Damsel in Distress", "Witness Zelda's escape and receive her heirloom.", OOT_ACH_ANY_ITEM, 1, "Item_Ocarina_Time", "", "") \
    X(40, "Last Breath", "Hear the dying guard's final message.", OOT_ACH_MANUAL, 0, "", "", "") \
    X(41, "Secrets Detector", "Collect 20 Gold Skulltula tokens.", OOT_ACH_ITEM_COUNT, 20, "Item_Token_Gold", "", "") \
    X(42, "A Woman's Best Friend", "Collect 30 Gold Skulltula tokens.", OOT_ACH_ITEM_COUNT, 30, "Item_Token_Gold", "", "") \
    X(43, "Hero of Time", "Transform into Adult Link.", OOT_ACH_ADULT, 0, "", "", "") \
    X(44, "Hook Me Away", "Obtain the Hookshot.", OOT_ACH_ANY_ITEM, 1, "Item_Hookshot", "", "") \
    X(45, "The Great Escape", "Ride Epona on Hyrule Field.", OOT_ACH_MANUAL, 0, "", "", "") \
    X(46, "Heat Resistant Tunic", "Obtain a Goron Tunic.", OOT_ACH_ANY_ITEM, 1, "Armor_Adult_Goron", "", "") \
    X(47, "Kiss That Frog", "Receive King Zora's kiss.", OOT_ACH_MANUAL, 0, "", "", "") \
    X(48, "Biggoron's Sword", "Obtain Biggoron's Sword.", OOT_ACH_ANY_ITEM, 1, "Weapon_Sword_Biggoron", "Item_Sword_Biggoron", "") \
    X(49, "Drunken Master", "Lower Phantom Ganon using only bow and bottles.", OOT_ACH_MANUAL, 0, "", "", "") \
    X(50, "Awakening", "Awake Saria and receive the Forest Medallion.", OOT_ACH_ANY_ITEM, 1, "Item_Medal_Forest", "", "") \
    X(51, "Sniper Elite", "Earn a prize at the adult shooting gallery.", OOT_ACH_ANY_ITEM, 1, "Item_Quiver_Medium", "", "") \
    X(52, "Hot Hot Hot", "Defeat Volvagia without the Goron Tunic.", OOT_ACH_MANUAL, 0, "", "", "") \
    X(53, "Eternal Brothers", "Awake Darunia and receive the Fire Medallion.", OOT_ACH_ANY_ITEM, 1, "Item_Medal_Fire", "", "") \
    X(54, "Pierre the Wanderer", "Learn the Scarecrow's Song.", OOT_ACH_MANUAL, 0, "", "", "") \
    X(55, "Day of the Tentacles", "Defeat Morpha without falling or being caught.", OOT_ACH_MANUAL, 0, "", "", "") \
    X(56, "Bride to Be", "Receive the Water Medallion from Ruto.", OOT_ACH_ANY_ITEM, 1, "Item_Medal_Water", "", "") \
    X(57, "The Flaming Arrow", "Obtain the Fire Arrow.", OOT_ACH_ANY_ITEM, 1, "Item_Arrow_Fire", "", "") \
    X(58, "Seeing Is Believing", "Obtain the Lens of Truth.", OOT_ACH_ANY_ITEM, 1, "Item_GlassTruth", "Armor_GlassTruth", "") \
    X(59, "Invisible One", "Defeat Bongo Bongo without the Lens or a hand trap.", OOT_ACH_MANUAL, 0, "", "", "") \
    X(60, "The Shadow of the Hylians", "Awake Impa and receive the Shadow Medallion.", OOT_ACH_ANY_ITEM, 1, "Item_Medal_Shadow", "", "") \
    X(61, "Gerudo's Fan Club", "Obtain the Gerudo Membership Card.", OOT_ACH_ANY_ITEM, 1, "Item_Token_Gerudo", "", "") \
    X(62, "Ultimate Horse Master", "Win the top horseback archery reward.", OOT_ACH_MANUAL, 0, "", "", "") \
    X(63, "Nayru's Love", "Learn Nayru's Love.", OOT_ACH_ANY_ITEM, 1, "Item_NayruLove", "", "") \
    X(64, "Musician", "Learn all twelve Ocarina songs.", OOT_ACH_ALL_SONGS, 12, "", "", "") \
    X(65, "Infamous Silver Gauntlets", "Obtain the Silver Gauntlets.", OOT_ACH_ANY_ITEM, 1, "Armor_Adult_Gauntlet_Silver", "Item_Gauntlet_Silver", "") \
    X(66, "Twins of Evil", "Defeat Twinrova without falling or reviving.", OOT_ACH_MANUAL, 0, "", "", "") \
    X(67, "Brainwashed", "Awake Nabooru and receive the Spirit Medallion.", OOT_ACH_ANY_ITEM, 1, "Item_Medal_Spirit", "", "") \
    X(68, "Graduate of Gerudo's Training Ground", "Finish the Training Ground and claim its prize.", OOT_ACH_ANY_ITEM, 1, "Item_Arrow_Ice", "", "") \
    X(69, "Poe Collector", "Catch all ten Big Poes and claim the fourth Bottle.", OOT_ACH_ITEM_COUNT, 4, "Item_Bottle", "", "") \
    X(70, "Drunkard", "Obtain all four Bottles.", OOT_ACH_ITEM_COUNT, 4, "Item_Bottle", "", "") \
    X(71, "Jump Over", "Complete Lon Lon Ranch's obstacle course.", OOT_ACH_MANUAL, 0, "", "", "") \
    X(72, "Wind Runner", "Finish the Running Man challenge in time.", OOT_ACH_MANUAL, 0, "", "", "") \
    X(73, "Ghost Chaser", "Finish Dampe's race in one minute.", OOT_ACH_MANUAL, 0, "", "", "") \
    X(74, "Expert Angler", "Catch a large fish as Adult Link.", OOT_ACH_MANUAL, 0, "", "", "") \
    X(75, "Mischievous Hero", "Make the Fishing Pond owner lose his hat.", OOT_ACH_MANUAL, 0, "", "", "") \
    X(76, "Accomplished Angler", "Catch the rare Hyrule Loach.", OOT_ACH_MANUAL, 0, "", "", "") \
    X(77, "To the Rescue", "Meet Princess Zelda before the final showdown.", OOT_ACH_MANUAL, 0, "", "", "") \
    X(78, "The Rock", "Gain the damage-halving defense upgrade.", OOT_ACH_ANY_ITEM, 1, "Item_FairyBless_DefenseDouble", "", "") \
    X(79, "Cartographer", "Finish the game with every map, compass, and boss key.", OOT_ACH_MANUAL, 0, "", "", "") \
    X(80, "King of Thieves", "Defeat Ganondorf without falling or using Fairies.", OOT_ACH_MANUAL, 0, "", "", "") \
    X(81, "My Last Breath", "Defeat Ganon with one heart or less, without Fairies or Bombs.", OOT_ACH_MANUAL, 0, "", "", "") \
    X(82, "Home Sweet Home", "Banish Ganon to the Evil Realm.", OOT_ACH_MANUAL, 0, "", "", "") \
    X(83, "The Fabulous Froggish Tenors", "Complete the Zora's River Frog minigame.", OOT_ACH_MANUAL, 0, "", "", "") \
    X(84, "Lifestyle and Stones", "Hear all 32 Gossip Stone rumors in one session.", OOT_ACH_MANUAL, 0, "", "", "") \
    X(85, "Bombchu", "Collect 40 Gold Skulltula tokens.", OOT_ACH_ITEM_COUNT, 40, "Item_Token_Gold", "", "") \
    X(86, "My Broken Heart", "Collect 50 Gold Skulltula tokens.", OOT_ACH_ITEM_COUNT, 50, "Item_Token_Gold", "", "") \
    X(87, "Family Reunion", "Collect all 100 Gold Skulltula tokens.", OOT_ACH_ITEM_COUNT, 100, "Item_Token_Gold", "", "") \
    X(88, "Plenty of Hearts", "Collect enough pieces for 20 hearts.", OOT_ACH_MANUAL, 0, "", "", "") \
    X(89, "Dangerously Delicious", "Beat King Dodongo hitless with three hearts and no bag bombs.", OOT_ACH_MANUAL, 0, "", "", "") \
    X(90, "Race Against the Clock", "Defeat Barinade within 1:51 with three hearts.", OOT_ACH_MANUAL, 0, "", "", "") \
    X(91, "Dodgeball", "Defeat Phantom Ganon without healing and with three hearts.", OOT_ACH_MANUAL, 0, "", "", "") \
    X(92, "Whac-A-Mole", "Beat Volvagia with the Hammer, no healing, and three hearts.", OOT_ACH_MANUAL, 0, "", "", "") \
    X(93, "Tentacles of the Deep", "Beat Morpha hitless without falling, with three hearts.", OOT_ACH_MANUAL, 0, "", "", "") \
    X(94, "Invisible Stalker", "Beat Bongo Bongo without the Lens or healing, with three hearts.", OOT_ACH_MANUAL, 0, "", "", "") \
    X(95, "Double Trouble", "Beat Twinrova with the Master Sword and Mirror Shield, no Fairy, and three hearts.", OOT_ACH_MANUAL, 0, "", "", "") \
    X(96, "Dark Lord", "Defeat Ganon without taking a hit and with three hearts.", OOT_ACH_MANUAL, 0, "", "", "") \
    X(97, "Blind Explorer", "Finish with three hearts and no maps or compasses.", OOT_ACH_MANUAL, 0, "", "", "")

#define OOT_LOCAL_ACHIEVEMENT_COUNT 98

#endif
