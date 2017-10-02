class State extends Config
    constructor: ($stateProvider, glMenuServiceProvider, bbSettingsServiceProvider) ->

        # Name of the state
        name = 'builders'

        # Menu configuration
        group =
            name: "builds"
            caption: 'Builds'
            icon: 'cogs'
            order: 10
        glMenuServiceProvider.addGroup group
        glMenuServiceProvider.setDefaultGroup group

        # Configuration
        cfg =
            group: "builds"
            caption: 'Builders'

        # Register new state
        state =
            controller: "#{name}Controller"
            templateUrl: "views/#{name}.html"
            name: name
            url: '/builders?tags'
            data: cfg
            reloadOnSearch: false

        $stateProvider.state(state)

        bbSettingsServiceProvider.addSettingsGroup
            name:'Builders'
            caption: 'Builders page related settings'
            items:[
                type:'bool'
                name:'show_old_builders'
                caption:'Show old builders'
                default_value: false
            ,
                type:'integer'
                name:'buildFetchLimit'
                caption:'Maximum number of builds to fetch'
                default_value: 200
            ]
