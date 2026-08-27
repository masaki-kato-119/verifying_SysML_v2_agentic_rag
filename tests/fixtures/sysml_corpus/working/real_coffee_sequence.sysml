private import ScalarValues::*;
private import Time::*;

// 型定義（元のファイルから）
item def Water;
item def CoffeeBeans;
item def Coffee;
item def Cup;

// 必要なブロック定義（participant用）
part def Person;
part def WaterBoiler;
part def BeanGrinder;
part def CoffeeBrewer;
part def SugarDispenser;
part def CupHolder;
part def BrewController;
part def WaterHeater;
part def BrewingUnit;
part def SugarUnit;
part def CupUnit;

// シーケンス図の定義（SysML v2仕様準拠版）
interaction def 'Coffee Brewing Sequence' {
    in sugarNeeded : Boolean;
    in initialWater : Water;
    in initialBeans : CoffeeBeans;
    out finalCoffee : Coffee;
    out resultCup : Cup;
    
    // 参加者（ライフライン）
    participant user : Person;
    participant boiler : WaterBoiler;
    participant grinder : BeanGrinder;
    participant brewer : CoffeeBrewer;
    participant sugarDispenser : SugarDispenser;
    participant cupHolder : CupHolder;
    
    // メッセージフロー（payloadブロック削除、単純なfrom-to形式）
    message start from user to boiler;
    message startGrinding from user to grinder;
    
    // 並行処理
    message boilComplete from boiler to brewer;
    message grindComplete from grinder to brewer;
    
    // 条件分岐（alt fragment使用）
    fragment alt sugarBranch {
        operand when sugarNeeded {
            message brewComplete from brewer to sugarDispenser;
            message addSugarRequest from sugarDispenser to sugarDispenser;
            message sugarAdded from sugarDispenser to cupHolder;
        }
        operand else {
            message skipSugar from brewer to cupHolder;
        }
    }
    
    message pourIntoCup from cupHolder to user;
}

// より詳細なシーケンス図（アクションベース）
interaction def 'Coffee Brewing Detailed Sequence' {
    in sugarNeeded : Boolean;
    in water : Water;
    in beans : CoffeeBeans;
    out finalCup : Cup;
    
    // ライフライン
    participant controller : BrewController;
    participant waterHeater : WaterHeater;
    participant beanGrinder : BeanGrinder;
    participant brewingUnit : BrewingUnit;
    participant sugarUnit : SugarUnit;
    participant cupUnit : CupUnit;
    
    // 開始
    message init from controller to controller;
    
    // 並行実行（par fragment使用）
    fragment par parallelProcessing {
        operand {
            message boilWaterCmd from controller to waterHeater;
            message hotWaterReady from waterHeater to brewingUnit;
        }
        operand {
            message grindBeansCmd from controller to beanGrinder;
            message groundBeansReady from beanGrinder to brewingUnit;
        }
    }
    
    // 抽出開始
    message startBrew from brewingUnit to brewingUnit;
    message brewedCoffeeReady from brewingUnit to controller;
    
    // 条件分岐: 砂糖の有無
    fragment alt sugarChoice {
        operand when sugarNeeded {
            message sendToSugar from controller to sugarUnit;
            message addSugarAction from sugarUnit to sugarUnit;
            message coffeeWithSugar from sugarUnit to cupUnit;
        }
        operand else {
            message sendToCup from controller to cupUnit;
        }
    }
    
    // カップに注ぐ
    message pourAction from cupUnit to cupUnit;
    message cupReady from cupUnit to controller;
    
    // 完了
    message complete from controller to controller;
}

// シンプルな制御フロー版
interaction def 'Coffee Brewing Simple' {
    in sugarNeeded : Boolean;
    
    // 実際のブロックをparticipantに使用
    participant boiler : WaterBoiler;
    participant grinder : BeanGrinder;
    participant brewer : CoffeeBrewer;
    participant dispenser : SugarDispenser;
    participant cup : CupHolder;
    
    // 並行開始
    fragment par preparation {
        operand {
            message boilWater from boiler to boiler;
            message waterReady from boiler to brewer;
        }
        operand {
            message grindBeans from grinder to grinder;
            message beansReady from grinder to brewer;
        }
    }
    
    // 抽出
    message brew from brewer to brewer;
    
    // 条件分岐
    fragment opt addSugarIfNeeded {
        operand when sugarNeeded {
            message addSugar from dispenser to dispenser;
        }
    }
    
    // 完成
    message pour from cup to cup;
}