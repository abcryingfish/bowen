// 《西游记》人物关系学习示例
// UTF-8 编码；可在 Neo4j Browser 中整段执行。
// 设计目标：50 个角色、可重复执行、便于 MATCH/OPTIONAL MATCH/路径查询练习。

// ---------- 1. 角色 ----------
UNWIND [
  {name:'唐僧', role:'取经人', faction:'大唐/佛门', home:'东土大唐', aliases:['陈玄奘','金蝉子']},
  {name:'孙悟空', role:'大徒弟', faction:'取经团队', home:'花果山', aliases:['齐天大圣','美猴王']},
  {name:'猪八戒', role:'二徒弟', faction:'取经团队', home:'高老庄', aliases:['猪悟能','天蓬元帅']},
  {name:'沙悟净', role:'三徒弟', faction:'取经团队', home:'流沙河', aliases:['沙僧','卷帘大将']},
  {name:'白龙马', role:'坐骑', faction:'取经团队', home:'西海龙宫', aliases:['玉龙三太子','敖烈']},
  {name:'观音菩萨', role:'取经总导演', faction:'佛门', home:'南海普陀山', aliases:['观世音']},
  {name:'如来佛祖', role:'佛祖', faction:'佛门', home:'灵山', aliases:['如来']},
  {name:'弥勒佛', role:'佛祖', faction:'佛门', home:'小西天', aliases:['东来佛祖']},
  {name:'文殊菩萨', role:'菩萨', faction:'佛门', home:'五台山', aliases:['文殊']},
  {name:'普贤菩萨', role:'菩萨', faction:'佛门', home:'峨眉山', aliases:['普贤']},
  {name:'唐太宗', role:'皇帝', faction:'大唐', home:'长安', aliases:['李世民']},
  {name:'魏征', role:'丞相/梦斩龙王', faction:'大唐', home:'长安', aliases:[]},
  {name:'金池长老', role:'和尚', faction:'人族', home:'观音禅院', aliases:[]},
  {name:'镇元大仙', role:'地仙之祖', faction:'道门', home:'五庄观', aliases:['镇元子']},
  {name:'太上老君', role:'道祖', faction:'天庭/道门', home:'兜率宫', aliases:['老君','太上道祖']},
  {name:'玉皇大帝', role:'天帝', faction:'天庭', home:'凌霄宝殿', aliases:['玉帝']},
  {name:'王母娘娘', role:'天后', faction:'天庭', home:'瑶池', aliases:['西王母']},
  {name:'二郎神', role:'天庭战神', faction:'天庭', home:'灌江口', aliases:['杨戬','清源妙道真君']},
  {name:'哪吒', role:'三坛海会大神', faction:'天庭', home:'陈塘关', aliases:['哪吒三太子']},
  {name:'李靖', role:'托塔天王', faction:'天庭', home:'陈塘关', aliases:['李天王']},
  {name:'太白金星', role:'天庭使者', faction:'天庭', home:'天宫', aliases:[]},
  {name:'嫦娥', role:'仙女', faction:'天庭', home:'广寒宫', aliases:[]},
  {name:'东海龙王', role:'龙王', faction:'龙宫', home:'东海龙宫', aliases:['敖广']},
  {name:'西海龙王', role:'龙王', faction:'龙宫', home:'西海龙宫', aliases:['敖闰']},
  {name:'泾河龙王', role:'龙王', faction:'龙族', home:'泾河', aliases:[]},
  {name:'牛魔王', role:'大力魔王', faction:'妖族', home:'积雷山', aliases:['平天大圣']},
  {name:'铁扇公主', role:'妖王夫人', faction:'妖族', home:'芭蕉洞', aliases:['罗刹女']},
  {name:'红孩儿', role:'妖王之子', faction:'妖族', home:'号山', aliases:['圣婴大王']},
  {name:'黄眉大王', role:'妖王', faction:'妖族', home:'小西天', aliases:['黄眉老佛']},
  {name:'金角大王', role:'妖王', faction:'妖族', home:'平顶山', aliases:[]},
  {name:'银角大王', role:'妖王', faction:'妖族', home:'平顶山', aliases:[]},
  {name:'白骨精', role:'妖怪', faction:'妖族', home:'白虎岭', aliases:['白骨夫人']},
  {name:'蜘蛛精', role:'妖怪', faction:'妖族', home:'盘丝洞', aliases:['盘丝大仙']},
  {name:'蝎子精', role:'妖怪', faction:'妖族', home:'毒敌山', aliases:[]},
  {name:'九灵元圣', role:'妖王', faction:'妖族', home:'竹节山', aliases:[]},
  {name:'青牛精', role:'妖王', faction:'妖族', home:'金兜山', aliases:['独角兕大王']},
  {name:'大鹏金翅雕', role:'妖王', faction:'妖族', home:'狮驼岭', aliases:['大鹏']},
  {name:'狮王', role:'妖王', faction:'妖族', home:'狮驼岭', aliases:['青毛狮子怪']},
  {name:'象王', role:'妖王', faction:'妖族', home:'狮驼岭', aliases:['黄牙老象']},
  {name:'黄袍怪', role:'妖王/星宿', faction:'妖族/天庭', home:'宝象国', aliases:['奎木狼']},
  {name:'玉兔精', role:'妖怪/仙子', faction:'妖族/天庭', home:'天竺国', aliases:['玉兔']},
  {name:'白鹿精', role:'妖怪', faction:'妖族', home:'比丘国', aliases:[]},
  {name:'老鼠精', role:'妖怪', faction:'妖族', home:'无底洞', aliases:['地涌夫人']},
  {name:'通天河灵感大王', role:'妖王', faction:'妖族/龙宫', home:'通天河', aliases:['灵感大王']},
  {name:'乌鸡国王', role:'国王', faction:'人族', home:'乌鸡国', aliases:[]},
  {name:'女儿国国王', role:'国王', faction:'人族', home:'西梁女国', aliases:[]},
  {name:'宝象国国王', role:'国王', faction:'人族', home:'宝象国', aliases:[]},
  {name:'高小姐', role:'凡人/家人', faction:'人族', home:'高老庄', aliases:['高翠兰']},
  {name:'紫霞仙子', role:'仙女', faction:'仙界', home:'盘丝洞旧址', aliases:['紫霞']},
  {name:'白晶晶', role:'妖怪', faction:'妖族', home:'盘丝洞', aliases:[]}
] AS r
MERGE (c:Character {name:r.name})
SET c.role=r.role, c.faction=r.faction, c.home=r.home, c.aliases=r.aliases;

// ---------- 2. 关系 ----------
// Neo4j 的 Relationship Type 使用稳定的英文分类，具体中文语义保存在 detail。
// 分类包括：师徒、同伴、指引、亲属、君臣、盟友、冲突、帮助、情感、一般关联。
UNWIND [
  ['唐僧','孙悟空','师徒','取经团队'], ['唐僧','猪八戒','师徒','取经团队'],
  ['唐僧','沙悟净','师徒','取经团队'], ['唐僧','白龙马','师徒/坐骑','取经团队'],
  ['孙悟空','猪八戒','师兄弟','取经团队'], ['孙悟空','沙悟净','师兄弟','取经团队'],
  ['猪八戒','沙悟净','师兄弟','取经团队'], ['孙悟空','白龙马','伙伴','取经团队'],
  ['观音菩萨','唐僧','指定取经人','取经计划'], ['观音菩萨','孙悟空','引导/约束','取经计划'],
  ['观音菩萨','猪八戒','收服/引导','取经计划'], ['观音菩萨','沙悟净','收服/引导','取经计划'],
  ['如来佛祖','观音菩萨','授命','佛门'], ['如来佛祖','孙悟空','镇压/点化','佛门'],
  ['文殊菩萨','乌鸡国王','救治/因果','佛门'], ['普贤菩萨','白象精','坐骑关系','佛门'],
  ['唐太宗','唐僧','委托取经','大唐'], ['魏征','泾河龙王','梦中斩杀','大唐因果'],
  ['唐太宗','魏征','君臣','大唐'],
  ['唐僧','金池长老','拜访','观音禅院'], ['孙悟空','金池长老','冲突','观音禅院'],
  ['孙悟空','镇元大仙','斗法后结交','五庄观'], ['镇元大仙','唐僧','人参果因果','五庄观'],
  ['孙悟空','太上老君','借助/求情','天庭'], ['太上老君','金角大王','法宝主人/部下','道门'],
  ['太上老君','银角大王','法宝主人/部下','道门'], ['玉皇大帝','孙悟空','招安/封官','天庭'],
  ['玉皇大帝','二郎神','君臣','天庭'], ['玉皇大帝','哪吒','君臣','天庭'],
  ['李靖','哪吒','父子','天庭'], ['二郎神','孙悟空','交战','天庭'],
  ['太白金星','孙悟空','招安建议','天庭'], ['嫦娥','猪八戒','旧日因果','天庭'],
  ['东海龙王','孙悟空','赠宝/相识','龙宫'], ['西海龙王','白龙马','父子','龙宫'],
  ['泾河龙王','唐太宗','赌约因果','大唐'], ['牛魔王','孙悟空','结拜兄弟/对手','妖族'],
  ['牛魔王','铁扇公主','夫妻','妖族'], ['牛魔王','红孩儿','父子','妖族'],
  ['铁扇公主','红孩儿','母子','妖族'], ['孙悟空','红孩儿','交战/降伏','妖族'],
  ['孙悟空','铁扇公主','借扇/冲突','火焰山'], ['孙悟空','黄眉大王','交战','小西天'],
  ['金角大王','银角大王','兄弟','平顶山'], ['孙悟空','金角大王','交战/降伏','平顶山'],
  ['孙悟空','银角大王','交战/降伏','平顶山'], ['白骨精','孙悟空','三打/消灭','白虎岭'],
  ['白骨精','唐僧','欺骗/离间','白虎岭'], ['蜘蛛精','孙悟空','交战','盘丝洞'],
  ['蜘蛛精','唐僧','擒拿/觊觎','盘丝洞'], ['蝎子精','唐僧','擒拿','毒敌山'],
  ['蝎子精','孙悟空','交战','毒敌山'], ['九灵元圣','黄眉大王','妖族关联','妖界'],
  ['青牛精','孙悟空','交战/收伏','金兜山'], ['太上老君','青牛精','坐骑关系','道门'],
  ['大鹏金翅雕','狮王','结拜兄弟','狮驼岭'], ['大鹏金翅雕','象王','结拜兄弟','狮驼岭'],
  ['狮王','象王','结拜兄弟','狮驼岭'], ['大鹏金翅雕','孙悟空','交战','狮驼岭'],
  ['黄袍怪','宝象国国王','占据/威胁','宝象国'], ['黄袍怪','玉皇大帝','前身/星宿','天庭'],
  ['玉兔精','女儿国国王','冒充/替代','天竺国'], ['玉兔精','嫦娥','逃跑/旧主','天庭'],
  ['太上老君','白鹿精','道门关联','比丘国'], ['老鼠精','唐僧','擒拿/觊觎','无底洞'],
  ['通天河灵感大王','西海龙王','龙宫关联','通天河'], ['通天河灵感大王','唐僧','索取祭品','通天河'],
  ['乌鸡国王','唐僧','求助/复国','乌鸡国'], ['女儿国国王','唐僧','爱慕/送行','西梁女国'],
  ['宝象国国王','唐僧','求助','宝象国'], ['高小姐','猪八戒','婚约/家庭','高老庄'],
  ['紫霞仙子','孙悟空','情感/因果','仙界'], ['白晶晶','孙悟空','情感/误会','盘丝洞']
] AS x
MATCH (a:Character {name:x[0]}), (b:Character {name:x[1]})
WITH a, b, x,
  CASE
    WHEN x[2] CONTAINS '师徒' OR x[2] CONTAINS '授命' OR x[2] CONTAINS '指定' THEN 'MASTER_OF'
    WHEN x[2] CONTAINS '师兄弟' OR x[2] CONTAINS '伙伴' THEN 'TEAMMATE'
    WHEN x[2] CONTAINS '引导' OR x[2] CONTAINS '点化' OR x[2] CONTAINS '收服' OR x[2] CONTAINS '收伏' THEN 'GUIDES'
    WHEN x[2] CONTAINS '父子' OR x[2] CONTAINS '母子' OR x[2] CONTAINS '夫妻' OR x[2] CONTAINS '家庭' THEN 'FAMILY'
    WHEN x[2] CONTAINS '君臣' OR x[2] CONTAINS '招安' OR x[2] CONTAINS '封官' THEN 'SERVES'
    WHEN x[2] CONTAINS '结拜' OR x[2] CONTAINS '结交' OR x[2] CONTAINS '兄弟' THEN 'ALLY'
    WHEN x[2] CONTAINS '交战' OR x[2] CONTAINS '冲突' OR x[2] CONTAINS '斩杀'
      OR x[2] CONTAINS '镇压' OR x[2] CONTAINS '消灭' OR x[2] CONTAINS '威胁' THEN 'FOUGHT'
    WHEN x[2] CONTAINS '帮助' OR x[2] CONTAINS '救治' OR x[2] CONTAINS '求助'
      OR x[2] CONTAINS '赠宝' OR x[2] CONTAINS '借助' THEN 'HELPS'
    WHEN x[2] CONTAINS '爱慕' OR x[2] CONTAINS '情感' OR x[2] CONTAINS '婚约' THEN 'ROMANTIC'
    ELSE 'CONNECTED_TO'
  END AS relationshipType
FOREACH (_ IN CASE WHEN relationshipType = 'MASTER_OF' THEN [1] ELSE [] END |
  MERGE (a)-[r:MASTER_OF {detail:x[2]}]->(b) SET r.context=x[3], r.dataset='xiyouji')
FOREACH (_ IN CASE WHEN relationshipType = 'TEAMMATE' THEN [1] ELSE [] END |
  MERGE (a)-[r:TEAMMATE {detail:x[2]}]->(b) SET r.context=x[3], r.dataset='xiyouji')
FOREACH (_ IN CASE WHEN relationshipType = 'GUIDES' THEN [1] ELSE [] END |
  MERGE (a)-[r:GUIDES {detail:x[2]}]->(b) SET r.context=x[3], r.dataset='xiyouji')
FOREACH (_ IN CASE WHEN relationshipType = 'FAMILY' THEN [1] ELSE [] END |
  MERGE (a)-[r:FAMILY {detail:x[2]}]->(b) SET r.context=x[3], r.dataset='xiyouji')
FOREACH (_ IN CASE WHEN relationshipType = 'SERVES' THEN [1] ELSE [] END |
  MERGE (a)-[r:SERVES {detail:x[2]}]->(b) SET r.context=x[3], r.dataset='xiyouji')
FOREACH (_ IN CASE WHEN relationshipType = 'ALLY' THEN [1] ELSE [] END |
  MERGE (a)-[r:ALLY {detail:x[2]}]->(b) SET r.context=x[3], r.dataset='xiyouji')
FOREACH (_ IN CASE WHEN relationshipType = 'FOUGHT' THEN [1] ELSE [] END |
  MERGE (a)-[r:FOUGHT {detail:x[2]}]->(b) SET r.context=x[3], r.dataset='xiyouji')
FOREACH (_ IN CASE WHEN relationshipType = 'HELPS' THEN [1] ELSE [] END |
  MERGE (a)-[r:HELPS {detail:x[2]}]->(b) SET r.context=x[3], r.dataset='xiyouji')
FOREACH (_ IN CASE WHEN relationshipType = 'ROMANTIC' THEN [1] ELSE [] END |
  MERGE (a)-[r:ROMANTIC {detail:x[2]}]->(b) SET r.context=x[3], r.dataset='xiyouji')
FOREACH (_ IN CASE WHEN relationshipType = 'CONNECTED_TO' THEN [1] ELSE [] END |
  MERGE (a)-[r:CONNECTED_TO {detail:x[2]}]->(b) SET r.context=x[3], r.dataset='xiyouji');

// ---------- 3. 可选：练习用的索引 ----------
CREATE INDEX character_name IF NOT EXISTS FOR (c:Character) ON (c.name);

// ---------- 4. 完成提示 ----------
MATCH (c:Character)
RETURN count(c) AS 角色数量;
