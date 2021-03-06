#!/usr/bin/env zsh

fit_model () {
    POPS=("cdc" "pmen" "maela")
    for training_pop in $POPS
    do
        TEST_POPS=("${(@)POPS:#$training_pop}") # subset array by removing training pop
        test_pop_1=${TEST_POPS[@]:0:1}
        test_pop_2=${TEST_POPS[@]:1:1}

        # run with testing populations in each order
        ./fit_models.py --model_type $1 --train_pop $training_pop --test_pop_1 $test_pop_1 --test_pop_2 $test_pop_2 --HMM_inference
        ./fit_models.py --model_type $1 --train_pop $training_pop --test_pop_1 $test_pop_2 --test_pop_2 $test_pop_1 --HMM_inference
    
        ./fit_models.py --model_type $1 --train_pop $training_pop --test_pop_1 $test_pop_1 --test_pop_2 $test_pop_2 --HMM_MIC_inference
        ./fit_models.py --model_type $1 --train_pop $training_pop --test_pop_1 $test_pop_2 --test_pop_2 $test_pop_1 --HMM_MIC_inference
    done
}

fit_model "random_forest"
