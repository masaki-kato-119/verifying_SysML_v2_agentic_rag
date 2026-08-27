    private import ScalarValues::*;
    // 型定義
    item def Water;
    item def CoffeeBeans;
    item def Coffee;
    item def Cup;
    // 'コーヒーを淹れる'アクティビティの定義
    action def 'Brew Coffee' {
        // アクティビティ全体のパラメータ
        in sugarNeeded : Boolean;
        inout water : Water;
        inout beans : CoffeeBeans;
        out finalCup : Cup;
        // アクションの定義
        action 'Boil Water' {
            inout w : Water;
        }
        action 'Grind Beans' {
            inout b : CoffeeBeans;
        }
        action 'Brew' {
            in hotWater : Water;
            in groundBeans : CoffeeBeans;
            out brewedCoffee : Coffee;
        }
        action 'Add Sugar' {
            inout coffee : Coffee;
        }
        action 'Pour into Cup' {
            in coffee : Coffee;
            out cup : Cup;
        }
        // フローの定義: 並行実行
        first start;
            then fork1;
            then 'Boil Water';
            then 'Grind Beans';
        first 'Boil Water' then join1;
        first 'Grind Beans' then join1;
        // オブジェクトフロー
        flow 'Boil Water'.w  to 'Brew'.hotWater;
        flow 'Grind Beans'.b to 'Brew'.groundBeans;
        join join1;
            then 'Brew';
        if sugarNeeded {
            first 'Brew' then 'Add Sugar';
            first 'Add Sugar' then 'Pour into Cup';
            flow 'Brew'.brewedCoffee to 'Add Sugar'.coffee;
            flow 'Add Sugar'.coffee to 'Pour into Cup'.coffee;
        } else {
            first 'Brew' then 'Pour into Cup';
            flow 'Brew'.brewedCoffee to 'Pour into Cup'.coffee;
        }
        first 'Pour into Cup';
            then done;
        flow 'Pour into Cup'.cup to finalCup;
    }